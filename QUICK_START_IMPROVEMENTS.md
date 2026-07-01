# Quick-Start Improvement Guide

## Priority 0: Critical Security (Week 1-2)

### 1. Add Authentication & Authorization

**Implementation Steps:**

```bash
# Install dependencies
pip install python-jose[cryptography] passlib[bcrypt] python-multipart redis
```

```python
# app/security/auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
import redis

security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService:
    def __init__(self):
        self.redis = redis.Redis(
            host=settings.REDIS_HOST or "localhost",
            port=settings.REDIS_PORT or 6379,
            db=0,
            decode_responses=True
        )
    
    def hash_password(self, password: str) -> str:
        return pwd_context.hash(password)
    
    def verify_password(self, plain: str, hashed: str) -> bool:
        return pwd_context.verify(plain, hashed)
    
    def create_access_token(self, data: dict) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=30)
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm="HS256")
    
    async def get_current_user(self, token: str = Depends(security)):
        try:
            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
            user_id: str = payload.get("sub")
            if user_id is None:
                raise HTTPException(status_code=401, detail="Invalid token")
            return user_id
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")

# Add to config.py
JWT_SECRET_KEY: str = Field(default="change-me-in-production", env="JWT_SECRET_KEY")
JWT_ALGORITHM: str = Field(default="HS256", env="JWT_ALGORITHM")
```

```python
# app/models/user.py
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    roles = Column(ARRAY(String), default=["user"])
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

```python
# Update main.py - add protected routes
from app.security.auth import AuthService

auth_service = AuthService()

@app.post("/api/v1/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not auth_service.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    access_token = auth_service.create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

# Protect existing routes
@router.post("/", dependencies=[Depends(auth_service.get_current_user)])
async def upload_resume(...):
    ...
```

**Environment Variables:**
```env
JWT_SECRET_KEY=your-super-secret-key-here
REDIS_HOST=localhost
REDIS_PORT=6379
```

---

### 2. Add Rate Limiting

```python
# app/api/middleware/rate_limit.py
from fastapi import Request, HTTPException, status
from redis import Redis
import time

class RateLimiter:
    def __init__(self):
        self.redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=1)
    
    async def check_limit(self, request: Request, limit: int = 100, window: int = 60):
        client_id = request.client.host
        key = f"rate_limit:{client_id}"
        
        current = self.redis.incr(key)
        if current == 1:
            self.redis.expire(key, window)
        
        if current > limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"}
            )

# Add to main.py
from app.api.middleware.rate_limit import RateLimiter

rate_limiter = RateLimiter()

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    await rate_limiter.check_limit(request)
    return await call_next(request)
```

---

### 3. Add HTTPS/TLS

```nginx
# nginx.conf
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    location / {
        proxy_pass http://app:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

```yaml
# docker-compose.yml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./certs:/etc/letsencrypt
    depends_on:
      - app
```

---

### 4. Add Secrets Management (AWS Secrets Manager)

```python
# app/security/secrets.py
import boto3
import json

class SecretsManager:
    def __init__(self):
        self.client = boto3.client('secretsmanager', region_name=settings.AWS_REGION)
    
    def get_secret(self, secret_name: str) -> dict:
        try:
            response = self.client.get_secret_value(SecretId=secret_name)
            return json.loads(response['SecretString'])
        except Exception as e:
            logger.error(f"Failed to get secret: {e}")
            raise

# Usage in config.py
secrets_manager = SecretsManager()
db_creds = secrets_manager.get_secret("resume-extractor/db")
DATABASE_URL = f"postgresql://{db_creds['username']}:{db_creds['password']}@{db_creds['host']}:5432/{db_creds['dbname']}"
```

---

## Priority 1: Scalability (Week 3-6)

### 5. Add Message Queue (Celery + RabbitMQ)

```bash
pip install celery redis
```

```python
# app/worker/celery_app.py
from celery import Celery

celery_app = Celery(
    "resume_extractor",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_time_limit=30 * 60,
)

# app/worker/tasks.py
from app.core.pipeline import extraction_pipeline
from app.database.resume_repository import ResumeRepository
from app.database.connection import get_db_context

@celery_app.task(bind=True)
def extract_resume_task(self, resume_id: str, file_path: str):
    with get_db_context() as db:
        repo = ResumeRepository(db)
        repo.mark_as_processing(resume_id)
        
        try:
            result = extraction_pipeline.run(file_path=file_path, resume_id=resume_id)
            repo.mark_as_completed(resume_id, result["schema"].model_dump(), result["timings"]["total"], result["overall_confidence"])
            return {"status": "completed"}
        except Exception as e:
            repo.mark_as_failed(resume_id, str(e))
            self.retry(exc=e, countdown=60, max_retries=3)
```

```yaml
# docker-compose.yml
services:
  rabbitmq:
    image: rabbitmq:3-management-alpine
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_DEFAULT_USER: admin
      RABBITMQ_DEFAULT_PASS: password
  
  celery_worker:
    build: .
    command: celery -A app.worker.celery_app worker --loglevel=info --concurrency=4
    depends_on:
      - rabbitmq
      - db
    volumes:
      - ./uploads:/app/uploads
```

---

### 6. Add Monitoring (Prometheus + Grafana)

```bash
pip install prometheus-fastapi-instrumentator opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi
```

```python
# app/monitoring/metrics.py
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# app/main.py
from app.monitoring.metrics import Instrumentator
Instrumentator().instrument(app).expose(app, endpoint="/metrics")
```

```yaml
# docker-compose.yml
services:
  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
  
  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    volumes:
      - grafana_data:/var/lib/grafana
```

---

### 7. Add Automated Backups

```python
# scripts/backup.py
import boto3
from datetime import datetime

class BackupManager:
    def __init__(self):
        self.rds = boto3.client('rds', region_name=settings.AWS_REGION)
    
    def create_snapshot(self, db_instance_id: str):
        snapshot_id = f"{db_instance_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.rds.create_db_snapshot(
            DBSnapshotIdentifier=snapshot_id,
            DBInstanceIdentifier=db_instance_id
        )
        return snapshot_id

# Add as Celery task
@celery_app.task(name="backup_database")
def backup_task():
    backup_manager = BackupManager()
    backup_manager.create_snapshot("resume-extractor-db")
```

---

## Priority 2: Compliance (Week 7-10)

### 8. Add Audit Logging

```python
# app/audit/audit_logger.py
from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True))
    action = Column(String(100))
    resource_type = Column(String(50))
    resource_id = Column(String(255))
    ip_address = Column(String(45))
    status = Column(String(20))
    details = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Middleware to log all requests
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    response = await call_next(request)
    
    # Log to audit table
    audit_log = AuditLog(
        user_id=getattr(request.state, 'user_id', None),
        action=f"{request.method} {request.url.path}",
        resource_type="api_request",
        status="success" if response.status_code < 400 else "failure",
        ip_address=request.client.host
    )
    db.add(audit_log)
    db.commit()
    
    return response
```

---

### 9. Add Data Retention Policy

```python
# app/governance/retention.py
from datetime import datetime, timedelta

class DataRetentionPolicy:
    def cleanup_expired_resumes(self):
        cutoff = datetime.utcnow() - timedelta(days=365)
        expired = db.query(Resume).filter(Resume.uploaded_at < cutoff).all()
        for resume in expired:
            file_handler.delete(resume.file_path)
            db.delete(resume)
        db.commit()

# Scheduled task
@celery_app.task(name="enforce_retention")
def retention_task():
    policy = DataRetentionPolicy()
    policy.cleanup_expired_resumes()
```

---

## Priority 3: Advanced Features (Week 11+)

### 10. Add Load Balancing

```yaml
# docker-compose.prod.yml
services:
  app:
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 4G
  
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
```

```nginx
# nginx.conf with load balancing
upstream app_servers {
    least_conn;
    server app:8000;
    server app:8000;
    server app:8000;
}

server {
    listen 443 ssl;
    location / {
        proxy_pass http://app_servers;
    }
}
```

---

### 11. Add Caching

```python
# app/cache/cache.py
from redis import Redis
import json

class CacheManager:
    def __init__(self):
        self.redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=2)
    
    def get(self, key: str):
        value = self.redis.get(key)
        return json.loads(value) if value else None
    
    def set(self, key: str, value: any, ttl: int = 3600):
        self.redis.setex(key, ttl, json.dumps(value))

# Use in routes
@router.get("/{resume_id}")
async def get_resume(resume_id: str, cache: CacheManager = Depends()):
    cached = cache.get(f"resume:{resume_id}")
    if cached:
        return cached
    
    resume = repo.get_by_id(resume_id)
    cache.set(f"resume:{resume_id}", resume)
    return resume
```

---

## Implementation Checklist

### Week 1
- [ ] Install security dependencies
- [ ] Implement JWT authentication
- [ ] Create User model and migration
- [ ] Add login endpoint
- [ ] Protect existing routes
- [ ] Test authentication flow

### Week 2
- [ ] Implement rate limiting middleware
- [ ] Set up Redis for rate limiting
- [ ] Configure nginx with SSL
- [ ] Obtain SSL certificate (Let's Encrypt)
- [ ] Test HTTPS configuration
- [ ] Add security headers

### Week 3-4
- [ ] Install Celery and RabbitMQ
- [ ] Create Celery tasks for extraction
- [ ] Update upload routes to use async tasks
- [ ] Add Celery worker to docker-compose
- [ ] Test async processing

### Week 5-6
- [ ] Install Prometheus and Grafana
- [ ] Add metrics endpoint
- [ ] Configure Prometheus scraping
- [ ] Create Grafana dashboards
- [ ] Set up alerting rules

### Week 7-8
- [ ] Create AuditLog model
- [ ] Add audit middleware
- [ ] Log all API requests
- [ ] Create audit log viewer

### Week 9-10
- [ ] Implement data retention policy
- [ ] Add scheduled cleanup task
- [ ] Test data deletion
- [ ] Document retention policy

### Week 11+
- [ ] Set up load balancer
- [ ] Configure multiple app instances
- [ ] Add caching layer
- [ ] Implement CDN
- [ ] Add WAF

---

## Quick Wins (Can be done in 1 day each)

1. **Add security headers** (1 hour)
2. **Add input validation** (2 hours)
3. **Add request ID tracking** (1 hour)
4. **Add structured logging** (2 hours)
5. **Add health check improvements** (1 hour)
6. **Add CORS hardening** (30 minutes)
7. **Add environment variable validation** (1 hour)
8. **Add dependency scanning** (2 hours)

---

## Cost Summary

| Improvement | Cost | Time |
|-------------|------|------|
| Authentication | $0 | 1 week |
| Rate Limiting | $0 | 2 days |
| HTTPS/TLS | $0 (Let's Encrypt) | 1 day |
| Secrets Manager | $0.40/month | 2 days |
| Message Queue | $0 (self-hosted) | 1 week |
| Monitoring | $0 (self-hosted) | 1 week |
| Backups | $50-150/month | 2 days |
| Audit Logging | $0 | 3 days |
| Data Retention | $0 | 2 days |
| Load Balancing | $75/month (ALB) | 1 week |

**Total First Month**: $0-225 (self-hosted) or $125-475 (AWS)
**Total Time**: 4-6 weeks for P0-P1 improvements

---

## Next Steps

1. **Start with authentication** - This is the most critical security gap
2. **Add rate limiting** - Protects against DoS while you implement other features
3. **Set up monitoring** - Gives visibility into system performance
4. **Implement async processing** - Enables scalability
5. **Add audit logging** - Foundation for compliance

For detailed implementation guides with Terraform configurations and complete code examples, see **ENTERPRISE_IMPROVEMENTS.md**.
