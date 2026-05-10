"""
web_app.py — ScholarBot Web Platform v3
All 4 recommendations: PostgreSQL, Opportunity model, Rec letters, Country mobility
"""
from __future__ import annotations
import json,logging,os,secrets,time,uuid
from datetime import datetime,timedelta
from jose import JWTError,jwt
from passlib.context import CryptContext
from pathlib import Path
from typing import Optional

from fastapi import FastAPI,HTTPException,Depends,UploadFile,File,BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse,FileResponse
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import (init_db,get_db,User,Application,Package,RecRequest,Job,
                      ApplicationStage,RecStatus,SessionLocal)

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger=logging.getLogger(__name__)

app=FastAPI(title="ScholarBot API",version="3.0.0")
@app.on_event("startup")
async def startup():
    init_db()
    # Load existing users into memory cache on startup
    try:
        from database import SessionLocal, User as DBUser
        db = SessionLocal()
        for u in db.query(DBUser).all():
            USERS[u.id] = u.to_dict(include_password=True)
        db.close()
        logger.info("Loaded %d users from database", len(USERS))
    except Exception as e:
        logger.warning("Could not load users from DB: %s", e)
    logger.info("ScholarBot v3 started")

def _decode_jwt(token: str):
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALG])
        return payload.get("sub")
    except JWTError:
        return None

def get_current_user(creds:HTTPAuthorizationCredentials=Depends(security),db:Session=Depends(get_db)):
    if not creds: raise HTTPException(401,"Not authenticated")
    uid = _decode_jwt(creds.credentials)
    if not uid: raise HTTPException(401,"Invalid or expired token")
    user = db.query(User).filter(User.id==uid).first()
    if not user: raise HTTPException(401,"User not found")
    return user

def optional_user(creds:HTTPAuthorizationCredentials=Depends(security),db:Session=Depends(get_db)):
    if not creds: return None
    uid = _decode_jwt(creds.credentials)
    if not uid: return None
    return db.query(User).filter(User.id==uid).first()

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_JWT_SECRET = os.environ.get("SECRET_KEY", secrets.token_hex(32))
_JWT_ALG = "HS256"
_JWT_DAYS = 7

def _hash_pw(pw: str) -> str:
    return _pwd.hash(pw)

def _check_pw(pw: str, hashed: str) -> bool:
    if ":" in hashed and len(hashed.split(":")[0]) == 32:
        import hashlib
        try:
            salt, h = hashed.split(":", 1)
            return hashlib.sha256(f"{salt}{pw}".encode()).hexdigest() == h
        except Exception:
            return False
    try:
        return _pwd.verify(pw, hashed)
    except Exception:
        return False

def _make_token(uid: str) -> str:
    exp = datetime.utcnow() + timedelta(days=_JWT_DAYS)
    return jwt.encode({"sub": uid, "exp": exp}, _JWT_SECRET, algorithm=_JWT_ALG)

def _get_llm():
    import requests as req
    key=os.environ.get("ANTHROPIC_API_KEY","")
    if key:
        def claude(s,u):
            r=req.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":"claude-haiku-4-5-20251001","max_tokens":1000,"system":s,"messages":[{"role":"user","content":u}]},timeout=30)
            return r.json()["content"][0]["text"]
        return claude
    base=os.environ.get("OLLAMA_BASE_URL","http://localhost:11434")
    model=os.environ.get("OLLAMA_MODEL","llama3.2:1b")
    try:
        req.get(f"{base}/api/tags",timeout=3)
        def ollama(s,u):
            r=req.post(f"{base}/api/generate",json={"model":model,"prompt":f"System: {s}\n\nUser: {u}","stream":False},timeout=120)
            return r.json().get("response","")
        return ollama
    except: pass
    return lambda s,u: "I am a motivated student committed to excellence and impact in my community."

def _count_by_type(opps):
    from collections import Counter; return dict(Counter(o.get("opportunity_type","scholarship") for o in opps))

def _days_until(d):
    try: return (datetime.strptime(d,"%Y-%m-%d")-datetime.utcnow()).days
    except: return 999

def _extract_from_doc(path,ext):
    import re; extracted={}
    try:
        if ext==".pdf":
            import fitz; doc=fitz.open(path); text=" ".join(p.get_text() for p in doc)
        elif ext in(".docx",".doc"):
            import docx; d=docx.Document(path); text=" ".join(p.text for p in d.paragraphs)
        else: return {}
        m=re.search(r"(?:gpa|cgpa)[:\s]+(\d+\.?\d*)",text.lower())
        if m: gpa=float(m.group(1)); gpa=round(gpa*4.0/5.0,2) if gpa>4 else gpa; extracted["gpa"]=min(4.0,gpa)
    except Exception as e: logger.debug("Doc extract: %s",e)
    return extracted

# ── Pydantic ──────────────────────────────────────────────────
class RegisterReq(BaseModel):
    name:str; email:str; password:str; degree_level:str="Graduate"
    major:str=""; school:str=""; nationality:str="Kenya"; gpa:float=0.0; financial_need:bool=False

class LoginReq(BaseModel):
    email:str; password:str

class ProfileUpdate(BaseModel):
    name:Optional[str]=None; major:Optional[str]=None; school:Optional[str]=None
    gpa:Optional[float]=None; graduation_year:Optional[int]=None; financial_need:Optional[bool]=None
    nationality:Optional[str]=None; languages:Optional[list[str]]=None; skills:Optional[list[str]]=None
    extracurriculars:Optional[list[str]]=None; personal_statement:Optional[str]=None
    demographic_tags:Optional[list[str]]=None

class RecReqCreate(BaseModel):
    opportunity_name:str; recommender_name:str; recommender_email:str
    recommender_title:str=""; recommender_institution:str=""; relationship_desc:str=""
    deadline:str=""; submission_link:str=""

class RecStatusUp(BaseModel):
    status:str

# ── Auth ──────────────────────────────────────────────────────
@app.post("/api/auth/register")
async def register(req:RegisterReq,db:Session=Depends(get_db)):
    if db.query(User).filter(User.email==req.email).first(): raise HTTPException(400,"Email already registered")
    u=User(id=f"user_{uuid.uuid4().hex[:10]}",name=req.name,email=req.email,password_hash=_hash_pw(req.password),
           degree_level=req.degree_level,major=req.major,school=req.school,nationality=req.nationality,
           gpa=req.gpa,financial_need=req.financial_need,languages=["English"],skills=[],
           extracurriculars=[],demographic_tags=[],personal_statement="")
    db.add(u); db.commit(); db.refresh(u)
    return {"token":_make_token(u.id),"user":u.to_dict()}

@app.post("/api/auth/login")
async def login(req:LoginReq,db:Session=Depends(get_db)):
    u=db.query(User).filter(User.email==req.email).first()
    if not u or not _check_pw(req.password,u.password_hash): raise HTTPException(401,"Invalid credentials")
    return {"token":_make_token(u.id),"user":u.to_dict()}

@app.get("/api/auth/me")
async def me(user:User=Depends(get_current_user)): return user.to_dict()

# ── Profile ───────────────────────────────────────────────────
@app.patch("/api/profile")
async def update_profile(upd:ProfileUpdate,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    for f,v in upd.dict(exclude_none=True).items(): setattr(user,f,v)
    user.updated_at=datetime.utcnow(); db.commit(); db.refresh(user); return user.to_dict()

@app.post("/api/profile/upload-doc")
async def upload_doc(file:UploadFile=File(...),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    ext=Path(file.filename).suffix.lower()
    if ext not in{".pdf",".docx",".doc",".jpg",".jpeg",".png"}: raise HTTPException(400,f"Unsupported: {ext}")
    d=Path(f"data/uploads/{user.id}"); d.mkdir(parents=True,exist_ok=True)
    p=d/f"{uuid.uuid4().hex[:8]}_{file.filename}"
    p.write_bytes(await file.read())
    ex=_extract_from_doc(str(p),ext)
    if ex:
        for k,v in ex.items(): setattr(user,k,v)
        db.commit()
        return {"message":"Uploaded and profile updated","extracted":ex}
    return {"message":"Uploaded"}

# ── Opportunities (Rec 2) ─────────────────────────────────────
@app.get("/api/opportunities")
async def get_opps(opp_type:Optional[str]=None,degree_level:Optional[str]=None,
                   field:Optional[str]=None,region:Optional[str]=None,
                   min_amount:Optional[int]=None,user:User=Depends(optional_user)):
    from engine.opportunity_db import get_for_profile
    p=user.to_dict() if user else {"degree_level":degree_level or "Graduate","nationality":"Kenya","financial_need":False}
    opps=get_for_profile(p)
    if opp_type: opps=[o for o in opps if o.get("opportunity_type")==opp_type]
    if min_amount: opps=[o for o in opps if o.get("amount_usd",0)>=min_amount]
    if field: opps=[o for o in opps if field.lower() in " ".join(o.get("tags",[])).lower() or field.lower() in o.get("name","").lower()]
    if region: opps=[o for o in opps if any(region.lower() in c.lower() for c in o.get("eligible_countries",[]))]
    return {"opportunities":opps,"count":len(opps)}

@app.get("/api/opportunities/matched")
async def get_matched_opps(user:User=Depends(get_current_user)):
    from engine.opportunity_db import rank_opportunities
    ranked=rank_opportunities(user.to_dict())
    return {"opportunities":ranked,"count":len(ranked),"total_potential_usd":sum(o.get("amount_usd",0) for o in ranked),"by_type":_count_by_type(ranked)}

@app.get("/api/opportunities/types")
async def opp_types():
    from engine.opportunity_db import opportunity_types_summary; return opportunity_types_summary()

@app.get("/api/opportunities/{opp_id}")
async def get_opp(opp_id:str,user:User=Depends(optional_user)):
    from engine.opportunity_db import get_by_id
    o=get_by_id(opp_id)
    if not o: raise HTTPException(404,"Not found")
    return o

# Backward compat
@app.get("/api/scholarships")
async def sch_compat(degree_level:Optional[str]=None,field:Optional[str]=None,region:Optional[str]=None,min_amount:Optional[int]=None,user:User=Depends(optional_user)):
    return await get_opps("scholarship",degree_level,field,region,min_amount,user)

@app.get("/api/scholarships/matched")
async def sch_matched_compat(user:User=Depends(get_current_user)):
    from engine.opportunity_db import rank_opportunities
    ranked=[o for o in rank_opportunities(user.to_dict()) if o.get("opportunity_type")=="scholarship"]
    return {"scholarships":ranked,"count":len(ranked),"total_potential_usd":sum(o.get("amount_usd",0) for o in ranked)}

# ── Country Mobility (Rec 4) ──────────────────────────────────
@app.get("/api/mobility")
async def all_mobility():
    from engine.opportunity_db import COUNTRY_MOBILITY; return COUNTRY_MOBILITY

@app.get("/api/mobility/{country}")
async def country_mobility(country:str):
    from engine.opportunity_db import COUNTRY_MOBILITY
    data=COUNTRY_MOBILITY.get(country) or next((v for k,v in COUNTRY_MOBILITY.items() if k.lower()==country.lower()),None)
    if not data: raise HTTPException(404,f"No mobility data for {country}")
    return {"country":country,**data}

# ── Readiness Score ───────────────────────────────────────────
@app.get("/api/readiness")
async def readiness(user:User=Depends(get_current_user)):
    from engine.scholarship_engine import compute_readiness_score; return compute_readiness_score(user.to_dict())

# ── Essays ────────────────────────────────────────────────────
@app.post("/api/essays/generate")
async def gen_essay(req:dict,bt:BackgroundTasks,user:User=Depends(get_current_user)):
    from engine.opportunity_db import get_by_id
    o=get_by_id(req.get("scholarship_id",""))
    if not o: raise HTTPException(404,"Opportunity not found")
    from database import SessionLocal as _SL
    _db = _SL()
    _job = Job(user_id=user.id,job_type="essay",status="running")
    _db.add(_job); _db.commit(); jid = _job.id; _db.close()
    bt.add_task(_essay_job,jid,o,user.to_dict(),req.get("tone","personal-narrative"),req.get("max_words",400))
    return {"job_id":jid,"status":"running","message":"Essay generation started"}

@app.get("/api/essays/{opp_id}")
async def get_essay(opp_id:str,user:User=Depends(get_current_user)):
    p=Path(f"data/packages/{user.id}/{opp_id}/essay.txt")
    if not p.exists(): raise HTTPException(404,"No essay — generate one first")
    return {"essay":p.read_text(encoding="utf-8"),"opp_id":opp_id}

# ── Packages ──────────────────────────────────────────────────
@app.post("/api/packages/prepare")
async def prep_packages(req:dict,bt:BackgroundTasks,user:User=Depends(get_current_user)):
    from database import SessionLocal as _SL
    _db = _SL()
    _job = Job(user_id=user.id,job_type="packages",status="running")
    _db.add(_job); _db.commit(); jid = _job.id; _db.close()
    bt.add_task(_packages_job,jid,user.to_dict(),req.get("top_n",5),req.get("opportunity_ids"))
    return {"job_id":jid,"status":"running","message":f"Preparing top {req.get('top_n',5)} packages"}

@app.get("/api/packages")
async def list_pkgs(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    pkgs=db.query(Package).filter(Package.user_id==user.id).order_by(Package.created_at.desc()).all()
    return {"packages":[p.to_dict() for p in pkgs]}

@app.get("/api/packages/{uid}/{pid}/briefing")
async def get_briefing(uid:str,pid:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.id!=uid: raise HTTPException(403,"Access denied")
    pkg=db.query(Package).filter(Package.id==pid).first()
    if not pkg: raise HTTPException(404,"Package not found")
    p=Path(pkg.briefing_path)
    if not p.exists(): raise HTTPException(404,"Briefing file missing")
    return HTMLResponse(p.read_text(encoding="utf-8"))

@app.get("/api/packages/{uid}/{pid}/essay")
async def get_pkg_essay(uid:str,pid:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.id!=uid: raise HTTPException(403,"Access denied")
    pkg=db.query(Package).filter(Package.id==pid).first()
    if not pkg: raise HTTPException(404,"Not found")
    return {"essay":pkg.essay_text or ""}

@app.get("/api/packages/{uid}/{pid}/download")
async def dl_package(uid:str,pid:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if user.id!=uid: raise HTTPException(403,"Access denied")
    pkg=db.query(Package).filter(Package.id==pid).first()
    if not pkg or not Path(pkg.briefing_path).exists(): raise HTTPException(404,"Not found")
    return FileResponse(pkg.briefing_path,media_type="text/html",filename=f"{pkg.scholarship_name[:30]}_briefing.html")

# ── Pipeline ──────────────────────────────────────────────────
@app.get("/api/pipeline")
async def get_pipeline(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    apps=db.query(Application).filter(Application.user_id==user.id).all()
    stages={s.value:[] for s in ApplicationStage}
    for a in apps: stages[a.stage.value].append(a.to_dict())
    return {"stages":stages,"counts":{k:len(v) for k,v in stages.items()},"total":len(apps)}

@app.patch("/api/pipeline/{app_id}/move")
async def move_stage(aid:str,data:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    a=db.query(Application).filter(Application.id==aid,Application.user_id==user.id).first()
    if not a: raise HTTPException(404,"Not found")
    try: a.stage=ApplicationStage(data.get("stage",a.stage))
    except ValueError: raise HTTPException(400,f"Invalid stage")
    a.updated_at=datetime.utcnow(); db.commit(); db.refresh(a); return a.to_dict()

@app.post("/api/pipeline/add")
async def add_pipeline(data:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    try: stage=ApplicationStage(data.get("stage","researching"))
    except ValueError: stage=ApplicationStage.researching
    a=Application(user_id=user.id,opportunity_id=data.get("scholarship_id",""),
                  scholarship_name=data.get("scholarship_name",""),amount_usd=data.get("amount_usd",0),
                  deadline=data.get("deadline",""),url=data.get("url",""),stage=stage,notes=data.get("notes",""))
    db.add(a); db.commit(); db.refresh(a); return a.to_dict()

# ── Applications ──────────────────────────────────────────────
@app.get("/api/applications")
async def list_apps(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    apps=db.query(Application).filter(Application.user_id==user.id).all()
    return {"applications":[a.to_dict() for a in apps],"total":len(apps),
            "submitted":sum(1 for a in apps if a.stage==ApplicationStage.submitted),
            "won":sum(1 for a in apps if a.stage==ApplicationStage.won),
            "total_won_usd":sum(a.amount_usd for a in apps if a.stage==ApplicationStage.won)}

@app.post("/api/applications/record")
async def record_app(data:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    a=Application(user_id=user.id,opportunity_id=data.get("scholarship_id",""),
                  scholarship_name=data.get("scholarship_name",""),amount_usd=data.get("amount_usd",0),
                  deadline=data.get("deadline",""),stage=ApplicationStage.submitted)
    db.add(a); user.applications_this_month=(user.applications_this_month or 0)+1
    db.commit(); db.refresh(a); return a.to_dict()

@app.patch("/api/applications/{aid}/outcome")
async def update_outcome(aid:str,data:dict,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    a=db.query(Application).filter(Application.id==aid,Application.user_id==user.id).first()
    if not a: raise HTTPException(404,"Not found")
    try: a.stage=ApplicationStage(data.get("status",a.stage))
    except ValueError: pass
    a.notes=data.get("notes",a.notes); a.outcome_date=datetime.utcnow(); a.updated_at=datetime.utcnow()
    db.commit(); db.refresh(a); return a.to_dict()

# ── Recommendation Letters (Rec 3) ────────────────────────────
@app.get("/api/recommendations")
async def list_recs(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    recs=db.query(RecRequest).filter(RecRequest.user_id==user.id).order_by(RecRequest.created_at.desc()).all()
    return {"recommendations":[r.to_dict() for r in recs],"total":len(recs),
            "received":sum(1 for r in recs if r.status==RecStatus.received),
            "pending":sum(1 for r in recs if r.status!=RecStatus.received)}

@app.post("/api/recommendations")
async def create_rec(req:RecReqCreate,bt:BackgroundTasks,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    rec=RecRequest(user_id=user.id,opportunity_name=req.opportunity_name,recommender_name=req.recommender_name,
                   recommender_email=req.recommender_email,recommender_title=req.recommender_title,
                   recommender_institution=req.recommender_institution,relationship_desc=req.relationship_desc,
                   deadline=req.deadline,submission_link=req.submission_link,status=RecStatus.requested)
    db.add(rec); db.commit(); db.refresh(rec)
    bt.add_task(_rec_letter_job,rec.id,user.to_dict(),req.dict())
    return {**rec.to_dict(),"message":"Request created. Draft letter being generated."}

@app.get("/api/recommendations/{rid}")
async def get_rec(rid:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    rec=db.query(RecRequest).filter(RecRequest.id==rid,RecRequest.user_id==user.id).first()
    if not rec: raise HTTPException(404,"Not found")
    return {**rec.to_dict(),"drafted_letter":rec.drafted_letter or "","briefing_text":rec.briefing_text or ""}

@app.patch("/api/recommendations/{rid}/status")
async def update_rec_status(rid:str,upd:RecStatusUp,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    rec=db.query(RecRequest).filter(RecRequest.id==rid,RecRequest.user_id==user.id).first()
    if not rec: raise HTTPException(404,"Not found")
    try: rec.status=RecStatus(upd.status)
    except ValueError: raise HTTPException(400,"Invalid status")
    if rec.status==RecStatus.received: rec.received_at=datetime.utcnow()
    rec.updated_at=datetime.utcnow(); db.commit(); db.refresh(rec); return rec.to_dict()

@app.delete("/api/recommendations/{rid}")
async def del_rec(rid:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    rec=db.query(RecRequest).filter(RecRequest.id==rid,RecRequest.user_id==user.id).first()
    if not rec: raise HTTPException(404,"Not found")
    db.delete(rec); db.commit(); return {"message":"Deleted"}

# ── Interview ─────────────────────────────────────────────────
@app.get("/api/interview/questions/{scholarship_slug}")
async def interview_qs(scholarship_slug:str,user:User=Depends(get_current_user)):
    from engine.interview_data import QUESTION_BANKS
    return {"scholarship":scholarship_slug,"questions":QUESTION_BANKS.get(scholarship_slug.lower(),QUESTION_BANKS["general"])}

@app.post("/api/interview/score")
async def interview_score(data:dict,user:User=Depends(get_current_user)):
    from engine.scholarship_engine import score_answer
    return score_answer(data.get("question",""),data.get("answer",""),user.to_dict(),data.get("scholarship","general"))

# ── Jobs ──────────────────────────────────────────────────────
@app.get("/api/jobs/{jid}")
async def get_job(jid:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    j = db.query(Job).filter(Job.id==jid,Job.user_id==user.id).first()
    if not j: raise HTTPException(404,"Job not found")
    return j.to_dict()

# ── Dashboard ─────────────────────────────────────────────────
@app.get("/api/dashboard")
async def dashboard(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from engine.opportunity_db import get_for_profile
    profile=user.to_dict(); matched=get_for_profile(profile)
    apps=db.query(Application).filter(Application.user_id==user.id).all()
    won=[a for a in apps if a.stage==ApplicationStage.won]
    submitted=[a for a in apps if a.stage==ApplicationStage.submitted]
    upcoming=[]
    for o in matched:
        d=_days_until(o.get("deadline",""))
        if 0<=d<=60: upcoming.append({"name":o["name"],"deadline":o["deadline"],"amount_usd":o.get("amount_usd",0),"days_left":d,"opportunity_type":o.get("opportunity_type","scholarship"),"url":o.get("url","")})
    upcoming.sort(key=lambda x:x["days_left"])
    return {"user":profile,"opportunities_matched":len(matched),"scholarships_matched":len([o for o in matched if o.get("opportunity_type")=="scholarship"]),
            "total_potential_usd":sum(o.get("amount_usd",0) for o in matched),"applications_submitted":len(submitted),
            "applications_won":len(won),"total_won_usd":sum(a.amount_usd for a in won),
            "upcoming_deadlines":upcoming[:5],"by_type":_count_by_type(matched)}

# ── Stats / Health ────────────────────────────────────────────
@app.get("/api/opportunities")
async def get_opportunities(
    type: str = None,
    min_amount: int = 0,
    user=Depends(optional_user),
):
    """Get all opportunity types — scholarships, fellowships, grants, etc."""
    profile = user if user else _default_profile()
    opps = match_opportunities(profile, opp_type=type, min_amount=min_amount)
    by_type = {}
    for o in opps:
        by_type.setdefault(o["opportunity_type"], []).append(o)
    return {
        "opportunities": opps,
        "count": len(opps),
        "by_type": {k: len(v) for k, v in by_type.items()},
        "total_potential_usd": sum(o["amount_usd"] for o in opps),
    }


@app.get("/api/health")
async def health(db:Session=Depends(get_db)):
    return {"status":"ok","users":db.query(User).count(),"version":"3.0.0","timestamp":datetime.utcnow().isoformat()}

@app.get("/api/stats")
async def stats(db:Session=Depends(get_db)):
    from engine.opportunity_db import get_all_opportunities,opportunity_types_summary
    opps=get_all_opportunities()
    return {"total_users":db.query(User).count(),"opportunities_in_db":len(opps),
            "total_potential_funding_usd":sum(o.get("amount_usd",0) for o in opps),"by_type":opportunity_types_summary(),"degree_levels":["Undergraduate","Graduate","Postgraduate"]}

# ── Static / SPA ──────────────────────────────────────────────
try: app.mount("/static",StaticFiles(directory="static"),name="static")
except: pass

@app.get("/",response_class=HTMLResponse)
async def spa():
    p=Path("static/index.html"); return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>ScholarBot API v3</h1>")

@app.get("/{path:path}",response_class=HTMLResponse)
async def spa_fb(path:str):
    if path.startswith("api/"): raise HTTPException(404)
    p=Path("static/index.html"); return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>ScholarBot</h1>")

# ── Background jobs ───────────────────────────────────────────
def _essay_job(jid,opp,profile,tone,max_words):
    try:
        from engine.scholarship_engine import generate_essay_for
        essay=generate_essay_for(opp,profile,tone,max_words)
        p=Path(f"data/packages/{profile['id']}/{opp['id']}"); p.mkdir(parents=True,exist_ok=True)
        (p/"essay.txt").write_text(essay,encoding="utf-8")
        from database import SessionLocal as _SL
        _db = _SL()
        _j = _db.query(Job).filter(Job.id==jid).first()
        if _j:
            _j.status="done"; _j.result={"essay":essay,"word_count":len(essay.split())}
            _j.completed_at=datetime.utcnow(); _db.commit()
        _db.close()
    except Exception as e:
        from database import SessionLocal as _SL
        _db = _SL()
        _j = _db.query(Job).filter(Job.id==jid).first()
        if _j: _j.status="failed"; _j.error=str(e); _db.commit()
        _db.close()

def _packages_job(jid,profile,top_n,opp_ids):
    try:
        from engine.opportunity_db import rank_opportunities,get_by_id
        from engine.scholarship_engine import generate_essay_for,_build_briefing_html
        opps=([get_by_id(i) for i in opp_ids if get_by_id(i)] if opp_ids else rank_opportunities(profile)[:top_n])
        uid=profile.get("id","anon"); base=Path(f"data/packages/{uid}"); created=[]
        db=SessionLocal()
        try:
            for o in opps:
                if not o: continue
                slug=o["name"].lower().replace(" ","_")[:28]; d=base/f"{slug}_{uuid.uuid4().hex[:4]}"; d.mkdir(parents=True,exist_ok=True)
                try: essay=generate_essay_for(o,profile)
                except: essay=f"[Essay for {o['name']} — write manually based on: {o.get('essay_prompt','')}]"
                dl=_days_until(o.get("deadline",""))
                (d/"essay.txt").write_text(essay,encoding="utf-8")
                briefing=_build_briefing_html(o,profile,essay,dl)
                bp=d/"briefing.html"; bp.write_text(briefing,encoding="utf-8")
                pkg=Package(user_id=uid,opportunity_id=o.get("id",""),scholarship_name=o.get("name",""),
                            amount_usd=o.get("amount_usd",0),deadline=o.get("deadline",""),days_left=dl,
                            url=o.get("url",""),essay_text=essay,briefing_path=str(bp),essay_path=str(d/"essay.txt"))
                db.add(pkg); created.append({"opportunity":o["name"],"days_left":dl})
            db.commit()
        finally: db.close()
        from database import SessionLocal as _SL
        _db = _SL()
        _j = _db.query(Job).filter(Job.id==jid).first()
        if _j:
            _j.status="done"; _j.result={"packages":created,"count":len(created)}
            _j.completed_at=datetime.utcnow(); _db.commit()
        _db.close()
    except Exception as e:
        logger.exception("Package job failed")
        from database import SessionLocal as _SL
        _db = _SL()
        _j = _db.query(Job).filter(Job.id==jid).first()
        if _j: _j.status="failed"; _j.error=str(e); _db.commit()
        _db.close()

def _rec_letter_job(rec_id,profile,req):
    db=SessionLocal()
    try:
        rec=db.query(RecRequest).filter(RecRequest.id==rec_id).first()
        if not rec: return
        llm=_get_llm(); name=profile.get("name",""); major=profile.get("major",""); school=profile.get("school","")
        gpa=profile.get("gpa",""); acts=", ".join(profile.get("extracurriculars",[])[:3])
        opp_name=req.get("opportunity_name","this opportunity"); rec_name=req.get("recommender_name","")
        rec_title=req.get("recommender_title",""); rel=req.get("relationship_desc","")
        try:
            letter=llm("Write a professional recommendation letter. Output only the letter text.",
                       f"Write a strong recommendation letter for {name} applying to {opp_name}.\nStudent: {major} at {school}, GPA {gpa}, activities: {acts}.\nRecommender: {rec_name}, {rec_title}. Relationship: {rel}.\nFirst person, specific, 300 words max. Include: how you know them, achievements, why they deserve this, strong recommendation.")
        except:
            letter=f"Dear Selection Committee,\n\nI am delighted to recommend {name} for {opp_name}. As their {rec_title}, I have observed their exceptional dedication to {major} at {school}.\n\n{name} consistently demonstrates intellectual curiosity and commitment to excellence. Their work reflects both technical competence and genuine care for their community.\n\nI recommend {name} without reservation.\n\nSincerely,\n{rec_name}\n{rec_title}"
        briefing=(f"RECOMMENDATION BRIEFING\nStudent: {name}\nApplying to: {opp_name}\nDeadline: {req.get('deadline','')}\n"
                  f"Submit at: {req.get('submission_link','TBC')}\n\nABOUT THE STUDENT\nDegree: {profile.get('degree_level','')} in {major}\n"
                  f"University: {school}\nGPA: {gpa}\nActivities: {acts}\nYour relationship: {rel}\n\nDRAFT LETTER\n{letter}")
        rec.drafted_letter=letter; rec.briefing_text=briefing; rec.status=RecStatus.drafted; rec.updated_at=datetime.utcnow()
        db.commit()
    except Exception as e: logger.error("Rec letter job failed: %s",e)
    finally: db.close()
