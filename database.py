"""
ScholarBot Web Platform v4 — Production Ready
"""
from __future__ import annotations
import logging, os, secrets, uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from passlib.context import CryptContext

from database import (
    init_db, get_db, SessionLocal,
    User, Application, Package, RecRequest, Job,
    ApplicationStage, RecStatus,
)

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger(__name__)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_JWT_SECRET = os.environ.get("SECRET_KEY", secrets.token_hex(32))
_JWT_ALG = "HS256"
_JWT_DAYS = 7
security = HTTPBearer(auto_error=False)

app = FastAPI(title="ScholarBot API", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    Path("data/packages").mkdir(parents=True, exist_ok=True)
    Path("static").mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("ScholarBot v4 started")

def _hash_pw(pw):
    return _pwd.hash(pw)

def _check_pw(pw, hashed):
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

def _make_token(uid):
    exp = datetime.utcnow() + timedelta(days=_JWT_DAYS)
    return jwt.encode({"sub": uid, "exp": exp}, _JWT_SECRET, algorithm=_JWT_ALG)

def _decode_jwt(token):
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALG]).get("sub")
    except JWTError:
        return None

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security),
                     db: Session = Depends(get_db)):
    if not creds: raise HTTPException(401, "Not authenticated")
    uid = _decode_jwt(creds.credentials)
    if not uid: raise HTTPException(401, "Invalid or expired token")
    user = db.query(User).filter(User.id == uid).first()
    if not user: raise HTTPException(401, "User not found")
    return user

def optional_user(creds: HTTPAuthorizationCredentials = Depends(security),
                   db: Session = Depends(get_db)):
    if not creds: return None
    uid = _decode_jwt(creds.credentials)
    if not uid: return None
    return db.query(User).filter(User.id == uid).first()

def _get_llm():
    import requests as req
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        def claude(s, u):
            try:
                r = req.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1000,
                          "system": s, "messages": [{"role": "user", "content": u}]},
                    timeout=30)
                return r.json()["content"][0]["text"]
            except Exception:
                return "I am a motivated student committed to excellence and community impact."
        return claude
    return lambda s, u: "I am a motivated student committed to excellence and community impact."

def _days_until(d):
    try: return (datetime.strptime(d, "%Y-%m-%d") - datetime.utcnow()).days
    except: return 999

class RegisterReq(BaseModel):
    name: str; email: str; password: str; degree_level: str = "Graduate"
    major: str = ""; school: str = ""; nationality: str = "Kenya"
    gpa: float = 0.0; financial_need: bool = False

class LoginReq(BaseModel):
    email: str; password: str

class ProfileUpdate(BaseModel):
    name: Optional[str]=None; major: Optional[str]=None; school: Optional[str]=None
    gpa: Optional[float]=None; financial_need: Optional[bool]=None
    nationality: Optional[str]=None; languages: Optional[list]=None
    skills: Optional[list]=None; extracurriculars: Optional[list]=None
    personal_statement: Optional[str]=None; demographic_tags: Optional[list]=None

class RecReqCreate(BaseModel):
    opportunity_name: str; recommender_name: str; recommender_email: str
    recommender_title: str = ""; recommender_institution: str = ""
    relationship_desc: str = ""; deadline: str = ""; submission_link: str = ""

class RecStatusUp(BaseModel):
    status: str

@app.post("/api/auth/register")
async def register(req: RegisterReq, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(400, "Email already registered")
    u = User(id=f"user_{uuid.uuid4().hex[:10]}", name=req.name, email=req.email,
             password_hash=_hash_pw(req.password), degree_level=req.degree_level,
             major=req.major, school=req.school, nationality=req.nationality,
             gpa=req.gpa, financial_need=req.financial_need,
             languages=["English"], skills=[], extracurriculars=[],
             demographic_tags=[], personal_statement="")
    db.add(u); db.commit(); db.refresh(u)
    return {"token": _make_token(u.id), "user": u.to_dict()}

@app.post("/api/auth/login")
async def login(req: LoginReq, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == req.email).first()
    if not u or not _check_pw(req.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"token": _make_token(u.id), "user": u.to_dict()}

@app.get("/api/auth/me")
async def me(user: User = Depends(get_current_user)): return user.to_dict()

@app.patch("/api/profile")
async def update_profile(upd: ProfileUpdate, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    for f, v in upd.dict(exclude_none=True).items(): setattr(user, f, v)
    user.updated_at = datetime.utcnow(); db.commit(); db.refresh(user)
    return user.to_dict()

@app.post("/api/profile/upload-doc")
async def upload_doc(file: UploadFile = File(...),
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    ext = Path(file.filename).suffix.lower()
    if ext not in {".pdf",".docx",".doc",".jpg",".jpeg",".png"}:
        raise HTTPException(400, f"Unsupported: {ext}")
    d = Path(f"data/uploads/{user.id}"); d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    p.write_bytes(await file.read())
    return {"message": "Document uploaded"}

@app.get("/api/readiness")
async def readiness(user: User = Depends(get_current_user)):
    from engine.scholarship_engine import compute_readiness_score
    return compute_readiness_score(user.to_dict())

@app.get("/api/opportunities")
async def get_opps(opp_type: Optional[str]=None, degree_level: Optional[str]=None,
                    field: Optional[str]=None, region: Optional[str]=None,
                    min_amount: Optional[int]=None,
                    user: User = Depends(optional_user)):
    from engine.opportunity_db import match_opportunities
    profile = user.to_dict() if user else {"degree_level": degree_level or "Graduate",
        "nationality": "Kenya", "financial_need": False, "gpa": 0, "major": ""}
    opps = match_opportunities(profile, opp_type=opp_type, min_amount=min_amount or 0)
    if field:
        opps = [o for o in opps if field.lower() in " ".join(o.get("tags",[])).lower()
                or field.lower() in o.get("name","").lower()]
    if region:
        opps = [o for o in opps if any(region.lower() in c.lower()
                for c in o.get("eligible_countries",[]))]
    by_type = {}
    for o in opps:
        by_type.setdefault(o["opportunity_type"], 0)
        by_type[o["opportunity_type"]] += 1
    return {"opportunities": opps, "count": len(opps), "by_type": by_type,
            "total_potential_usd": sum(o["amount_usd"] for o in opps)}

@app.get("/api/scholarships")
async def get_scholarships(degree_level: Optional[str]=None, field: Optional[str]=None,
                            region: Optional[str]=None, min_amount: Optional[int]=None,
                            user: User = Depends(optional_user)):
    result = await get_opps("scholarship", degree_level, field, region, min_amount, user)
    # Return with "scholarships" key for frontend compatibility
    return {"scholarships": result.get("opportunities", []),
            "count": result.get("count", 0),
            "total_potential_usd": result.get("total_potential_usd", 0)}

@app.get("/api/scholarships/matched")
async def matched_scholarships(user: User = Depends(get_current_user)):
    from engine.opportunity_db import match_opportunities
    opps = match_opportunities(user.to_dict(), opp_type="scholarship")
    return {"scholarships": opps, "count": len(opps),
            "total_potential_usd": sum(o["amount_usd"] for o in opps)}

@app.post("/api/essays/generate")
async def gen_essay(req: dict, bt: BackgroundTasks,
                     user: User = Depends(get_current_user)):
    from engine.opportunity_db import load_all_opportunities
    opp_id = req.get("scholarship_id","")
    opp = next((o for o in load_all_opportunities() if o["id"]==opp_id), None)
    if not opp: raise HTTPException(404, "Opportunity not found")
    db = SessionLocal()
    job = Job(user_id=user.id, job_type="essay", status="running")
    db.add(job); db.commit(); jid = job.id; db.close()
    bt.add_task(_essay_job, jid, opp, user.to_dict(),
                req.get("tone","personal-narrative"), req.get("max_words",400))
    return {"job_id": jid, "status": "running", "message": "Essay generation started"}

@app.post("/api/packages/prepare")
async def prep_packages(req: dict, bt: BackgroundTasks,
                         user: User = Depends(get_current_user)):
    db = SessionLocal()
    job = Job(user_id=user.id, job_type="packages", status="running")
    db.add(job); db.commit(); jid = job.id; db.close()
    bt.add_task(_packages_job, jid, user.to_dict(),
                req.get("top_n",5), req.get("opportunity_ids"))
    return {"job_id": jid, "status": "running",
            "message": f"Preparing top {req.get('top_n',5)} packages"}

@app.get("/api/packages")
async def list_pkgs(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    pkgs = db.query(Package).filter(Package.user_id==user.id)\
             .order_by(Package.created_at.desc()).all()
    return {"packages": [p.to_dict() for p in pkgs]}

@app.get("/api/packages/{uid}/{pid}/briefing", response_class=HTMLResponse)
async def get_briefing(uid: str, pid: str, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    if user.id != uid: raise HTTPException(403, "Access denied")
    pkg = db.query(Package).filter(Package.id==pid).first()
    if not pkg: raise HTTPException(404, "Package not found")
    return HTMLResponse(pkg.briefing_html or "<p>Briefing not available</p>")

@app.get("/api/packages/{uid}/{pid}/essay")
async def get_pkg_essay(uid: str, pid: str, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    if user.id != uid: raise HTTPException(403, "Access denied")
    pkg = db.query(Package).filter(Package.id==pid).first()
    if not pkg: raise HTTPException(404, "Not found")
    return {"essay": pkg.essay_text or ""}

@app.get("/api/pipeline")
async def get_pipeline(user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.user_id==user.id).all()
    stages = {s.value: [] for s in ApplicationStage}
    for a in apps: stages[a.stage.value].append(a.to_dict())
    won_total = sum(a.amount_usd for a in apps if a.stage==ApplicationStage.won)
    return {"stages": stages, "counts": {k:len(v) for k,v in stages.items()},
            "total": len(apps), "won_total_usd": won_total}

@app.patch("/api/pipeline/{app_id}/move")
async def move_stage(app_id: str, data: dict, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id==app_id,
        Application.user_id==user.id).first()
    if not a: raise HTTPException(404, "Application not found")
    try: a.stage = ApplicationStage(data.get("stage", a.stage.value))
    except ValueError: raise HTTPException(400, "Invalid stage")
    a.updated_at = datetime.utcnow(); db.commit(); db.refresh(a)
    return a.to_dict()

@app.post("/api/pipeline/add")
async def add_pipeline(data: dict, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    try: stage = ApplicationStage(data.get("stage","researching"))
    except ValueError: stage = ApplicationStage.researching
    a = Application(user_id=user.id, opportunity_id=data.get("scholarship_id",""),
                    scholarship_name=data.get("scholarship_name",""),
                    opportunity_type=data.get("opportunity_type","scholarship"),
                    amount_usd=float(data.get("amount_usd",0)),
                    deadline=data.get("deadline",""), url=data.get("url",""),
                    stage=stage, notes=data.get("notes",""))
    db.add(a); db.commit(); db.refresh(a)
    return a.to_dict()

@app.get("/api/applications")
async def list_apps(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.user_id==user.id).all()
    won = [a for a in apps if a.stage==ApplicationStage.won]
    submitted = [a for a in apps if a.stage==ApplicationStage.submitted]
    return {"applications": [a.to_dict() for a in apps], "total": len(apps),
            "submitted": len(submitted), "won": len(won),
            "total_applied_usd": sum(a.amount_usd for a in submitted),
            "total_won_usd": sum(a.amount_usd for a in won)}

@app.post("/api/applications/record")
async def record_app(data: dict, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    a = Application(user_id=user.id, opportunity_id=data.get("scholarship_id",""),
                    scholarship_name=data.get("scholarship_name",""),
                    opportunity_type=data.get("opportunity_type","scholarship"),
                    amount_usd=float(data.get("amount_usd",0)),
                    deadline=data.get("deadline",""), url=data.get("url",""),
                    stage=ApplicationStage.submitted, submitted_at=datetime.utcnow())
    db.add(a)
    user.applications_this_month = (user.applications_this_month or 0) + 1
    db.commit(); db.refresh(a)
    return a.to_dict()

@app.patch("/api/applications/{app_id}/outcome")
async def update_outcome(app_id: str, data: dict,
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id==app_id,
        Application.user_id==user.id).first()
    if not a: raise HTTPException(404, "Application not found")
    try: a.stage = ApplicationStage(data.get("status", a.stage.value))
    except ValueError: pass
    a.notes = data.get("notes", a.notes)
    a.outcome_date = datetime.utcnow(); a.updated_at = datetime.utcnow()
    db.commit(); db.refresh(a)
    return a.to_dict()

@app.get("/api/recommendations")
async def list_recs(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    recs = db.query(RecRequest).filter(RecRequest.user_id==user.id)\
             .order_by(RecRequest.created_at.desc()).all()
    return {"recommendations": [r.to_dict() for r in recs], "total": len(recs),
            "received": sum(1 for r in recs if r.status==RecStatus.received),
            "pending": sum(1 for r in recs if r.status!=RecStatus.received)}

@app.post("/api/recommendations")
async def create_rec(req: RecReqCreate, bt: BackgroundTasks,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    rec = RecRequest(user_id=user.id, opportunity_name=req.opportunity_name,
                     recommender_name=req.recommender_name,
                     recommender_email=req.recommender_email,
                     recommender_title=req.recommender_title,
                     recommender_institution=req.recommender_institution,
                     relationship_desc=req.relationship_desc, deadline=req.deadline,
                     submission_link=req.submission_link, status=RecStatus.requested)
    db.add(rec); db.commit(); db.refresh(rec)
    bt.add_task(_rec_letter_job, rec.id, user.to_dict(), req.dict())
    return {**rec.to_dict(), "message": "Request created. Draft letter being generated."}

@app.patch("/api/recommendations/{rid}/status")
async def update_rec_status(rid: str, upd: RecStatusUp,
                             user: User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    rec = db.query(RecRequest).filter(RecRequest.id==rid,
        RecRequest.user_id==user.id).first()
    if not rec: raise HTTPException(404, "Not found")
    try: rec.status = RecStatus(upd.status)
    except ValueError: raise HTTPException(400, "Invalid status")
    if rec.status == RecStatus.received: rec.received_at = datetime.utcnow()
    rec.updated_at = datetime.utcnow(); db.commit(); db.refresh(rec)
    return rec.to_dict()

@app.get("/api/interview/questions/{scholarship_slug}")
async def interview_qs(scholarship_slug: str,
                        user: User = Depends(get_current_user)):
    from engine.interview_data import QUESTION_BANKS
    return {"scholarship": scholarship_slug,
            "questions": QUESTION_BANKS.get(scholarship_slug.lower(),
                                             QUESTION_BANKS["general"])}

@app.post("/api/interview/score")
async def interview_score(data: dict, user: User = Depends(get_current_user)):
    from engine.scholarship_engine import score_answer
    return score_answer(data.get("question",""), data.get("answer",""),
                        user.to_dict(), data.get("scholarship","general"))

@app.get("/api/jobs/{jid}")
async def get_job(jid: str, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    j = db.query(Job).filter(Job.id==jid, Job.user_id==user.id).first()
    if not j: raise HTTPException(404, "Job not found")
    return j.to_dict()

@app.get("/api/dashboard")
async def dashboard(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    from engine.opportunity_db import match_opportunities
    profile = user.to_dict()
    matched = match_opportunities(profile)
    apps = db.query(Application).filter(Application.user_id==user.id).all()
    won = [a for a in apps if a.stage==ApplicationStage.won]
    submitted = [a for a in apps if a.stage==ApplicationStage.submitted]
    upcoming = sorted(
        [{"name":o["name"],"deadline":o["deadline"],"amount_usd":o.get("amount_usd",0),
          "days_left":_days_until(o.get("deadline",""))}
         for o in matched if 0<=_days_until(o.get("deadline",""))<=60],
        key=lambda x: x["days_left"])
    return {"user": profile, "scholarships_matched": len(matched),
            "total_potential_usd": sum(o["amount_usd"] for o in matched),
            "applications_submitted": len(submitted), "applications_won": len(won),
            "total_won_usd": sum(a.amount_usd for a in won),
            "upcoming_deadlines": upcoming[:5]}

@app.get("/api/health")
async def health(db: Session = Depends(get_db)):
    return {"status":"ok","users":db.query(User).count(),
            "version":"4.0.0","timestamp":datetime.utcnow().isoformat()}

@app.get("/api/stats")
async def stats(db: Session = Depends(get_db)):
    from engine.opportunity_db import load_all_opportunities
    opps = load_all_opportunities()
    by_type = {}
    for o in opps:
        by_type.setdefault(o["opportunity_type"],0); by_type[o["opportunity_type"]]+=1
    return {"total_users":db.query(User).count(),"opportunities_in_db":len(opps),
            "total_potential_funding_usd":sum(o["amount_usd"] for o in opps),
            "by_type":by_type,"degree_levels":["Undergraduate","Graduate","Postgraduate"]}

@app.get("/", response_class=HTMLResponse)
async def spa():
    p = Path("static/index.html")
    if p.exists(): return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ScholarBot API v4</h1><p>Frontend loading...</p>")

@app.get("/{path:path}", response_class=HTMLResponse)
async def spa_fallback(path: str):
    if path.startswith("api/"): raise HTTPException(404)
    p = Path("static/index.html")
    if p.exists(): return HTMLResponse(p.read_text(encoding="utf-8"))
    raise HTTPException(404)

def _update_job(jid, status, result=None, error=None):
    db = SessionLocal()
    try:
        j = db.query(Job).filter(Job.id==jid).first()
        if j:
            j.status=status
            if result is not None: j.result=result
            if error is not None: j.error=error
            j.completed_at=datetime.utcnow(); db.commit()
    finally: db.close()

def _essay_job(jid, opp, profile, tone, max_words):
    try:
        from engine.scholarship_engine import generate_essay_for
        essay = generate_essay_for(opp, profile, tone, max_words)
        _update_job(jid,"done",result={"essay":essay,"word_count":len(essay.split())})
    except Exception as e:
        _update_job(jid,"failed",error=str(e))

def _packages_job(jid, profile, top_n, opp_ids):
    try:
        from engine.opportunity_db import match_opportunities, load_all_opportunities
        from engine.scholarship_engine import generate_essay_for
        if opp_ids:
            all_opps = load_all_opportunities()
            opps = [o for o in all_opps if o["id"] in opp_ids]
        else:
            opps = match_opportunities(profile)[:top_n]
        uid = profile.get("id","anon"); created=[]; db=SessionLocal()
        try:
            for o in opps:
                if not o: continue
                try: essay = generate_essay_for(o, profile)
                except: essay = f"Essay for {o['name']}.\n\nPrompt: {o.get('essay_prompt','')}\n\nPlease personalise this essay."
                dl = _days_until(o.get("deadline",""))
                briefing = _build_briefing(o, profile, essay, dl)
                pkg = Package(user_id=uid, opportunity_id=o.get("id",""),
                              scholarship_name=o.get("name",""),
                              opportunity_type=o.get("opportunity_type","scholarship"),
                              amount_usd=o.get("amount_usd",0),
                              deadline=o.get("deadline",""), days_left=dl,
                              url=o.get("url",""), essay_text=essay,
                              briefing_html=briefing)
                db.add(pkg); created.append({"opportunity":o["name"],"days_left":dl})
            db.commit()
        finally: db.close()
        _update_job(jid,"done",result={"packages":created,"count":len(created)})
    except Exception as e:
        logger.exception("Package job failed")
        _update_job(jid,"failed",error=str(e))

def _rec_letter_job(rec_id, profile, req):
    db = SessionLocal()
    try:
        rec = db.query(RecRequest).filter(RecRequest.id==rec_id).first()
        if not rec: return
        llm=_get_llm(); name=profile.get("name",""); major=profile.get("major","")
        school=profile.get("school",""); gpa=profile.get("gpa","")
        acts=", ".join((profile.get("extracurriculars") or [])[:3])
        opp_name=req.get("opportunity_name","this opportunity")
        rec_name=req.get("recommender_name",""); rec_title=req.get("recommender_title","")
        rel=req.get("relationship_desc","")
        try:
            letter=llm("Write a professional recommendation letter. Output only the letter text.",
                f"Write a strong 300-word recommendation for {name} applying to {opp_name}. "
                f"Student: {major} at {school}, GPA {gpa}, activities: {acts}. "
                f"Recommender: {rec_name}, {rec_title}. Relationship: {rel}. First person, specific.")
        except:
            letter=(f"Dear Selection Committee,\n\nI am delighted to recommend {name} for "
                    f"{opp_name}. As their {rec_title}, I have witnessed their exceptional "
                    f"dedication to {major} at {school}.\n\n{name} consistently demonstrates "
                    f"intellectual curiosity and commitment to excellence.\n\n"
                    f"Sincerely,\n{rec_name}\n{rec_title}")
        briefing=(f"RECOMMENDATION BRIEFING\nStudent: {name}\nApplying to: {opp_name}\n"
                  f"Deadline: {req.get('deadline','TBC')}\nSubmit at: {req.get('submission_link','TBC')}\n\n"
                  f"ABOUT THE STUDENT\nDegree: {profile.get('degree_level','')} in {major}\n"
                  f"University: {school} | GPA: {gpa}\nActivities: {acts}\n"
                  f"Your relationship: {rel}\n\nDRAFT LETTER\n{'='*50}\n{letter}")
        rec.drafted_letter=letter; rec.briefing_text=briefing
        rec.updated_at=datetime.utcnow(); db.commit()
    except Exception as e: logger.error("Rec letter job failed: %s",e)
    finally: db.close()

def _build_briefing(opp, profile, essay, days_left):
    urg="#dc2626" if days_left<=7 else "#d97706" if days_left<=30 else "#059669"
    fields={"Full name":profile.get("name",""),"Email":profile.get("email",""),
            "University":profile.get("school",""),"Degree":profile.get("degree_level",""),
            "Major":profile.get("major",""),"GPA":str(profile.get("gpa","")),
            "Country":profile.get("nationality",""),"Financial need":"Yes" if profile.get("financial_need") else "No"}
    rows="".join(f"<tr><td style='padding:7px 12px;font-weight:500;color:#555;width:140px;border-bottom:1px solid #f0f0f0'>{k}</td><td style='padding:7px 12px;border-bottom:1px solid #f0f0f0'><span onclick=\"navigator.clipboard.writeText('{v}')\" style='cursor:pointer;background:#f8f8f8;padding:3px 8px;border-radius:4px;font-family:monospace;font-size:13px' title='Click to copy'>{v}</span></td></tr>" for k,v in fields.items() if v)
    essay_safe=essay.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{opp['name']}</title>
<style>body{{font-family:-apple-system,sans-serif;background:#f9f9f7;margin:0}}
.hdr{{background:#1a1a2e;color:#fff;padding:1.5rem 2rem;display:flex;justify-content:space-between}}
.hdr h1{{font-size:18px;font-weight:500;margin:0}}.urg{{background:{urg};color:#fff;padding:4px 12px;border-radius:20px;font-size:12px}}
.body{{max-width:760px;margin:0 auto;padding:2rem}}.card{{background:#fff;border:1px solid #e8e8e0;border-radius:12px;margin-bottom:1.25rem;overflow:hidden}}
.ch{{background:#f5f5f0;padding:.75rem 1.25rem;font-size:13px;font-weight:500;border-bottom:1px solid #e8e8e0}}.cb{{padding:1.25rem}}
.btn{{display:inline-block;background:#1a1a2e;color:#fff;padding:8px 18px;border-radius:6px;text-decoration:none;font-size:13px}}
table{{width:100%;border-collapse:collapse}}.essay{{background:#f8f8f8;border:1px solid #e0e0e0;border-radius:8px;padding:1rem;font-size:14px;line-height:1.7;white-space:pre-wrap}}</style>
</head><body>
<div class="hdr"><div><h1>{opp['name']}</h1><p style="margin:4px 0 0;opacity:.7;font-size:13px">${opp.get('amount_usd',0):,.0f} | Deadline: {opp.get('deadline','')}</p></div><span class="urg">{days_left} days left</span></div>
<div class="body">
<div class="card"><div class="ch">Step 1 — Open application form</div><div class="cb"><a class="btn" href="{opp.get('url','')}" target="_blank">Open Application Form &rarr;</a></div></div>
<div class="card"><div class="ch">Step 2 — Copy your details (click any value)</div><div class="cb"><table>{rows}</table></div></div>
<div class="card"><div class="ch">Step 3 — Paste your essay</div><div class="cb"><p style="font-size:12px;color:#888;margin-bottom:.75rem"><em>{opp.get('essay_prompt','')[:120]}</em></p><div class="essay">{essay_safe}</div></div></div>
</div></body></html>"""
