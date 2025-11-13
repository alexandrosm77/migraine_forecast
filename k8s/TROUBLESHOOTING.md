# Kubernetes Troubleshooting Guide

Quick reference for debugging the migraine forecast application.

## Quick Status

Check everything:
```bash
kubectl get all -n migraine-forecast
```

Check pods:
```bash
kubectl get pods -n migraine-forecast
```

Check service:
```bash
kubectl get svc -n migraine-forecast
```

## View Logs

### Web Logs
```bash
# Recent logs
kubectl logs -n migraine-forecast -l component=web --tail=50

# Follow in real-time
kubectl logs -n migraine-forecast -l component=web -f
```

### Cron Logs
```bash
# Recent logs
kubectl logs -n migraine-forecast -l component=cron --tail=50

# Follow in real-time
kubectl logs -n migraine-forecast -l component=cron -f
```

### Migration Logs
```bash
kubectl logs -n migraine-forecast job/migraine-migration
```

### Backup Logs
```bash
# List all jobs
kubectl get jobs -n migraine-forecast

# View specific backup job
kubectl logs -n migraine-forecast job/migraine-backup-<timestamp>
```

## Get Shell Access

### Access Web Pod
```bash
kubectl exec -it -n migraine-forecast deployment/migraine-forecast-web -- /bin/bash
```

### Access Cron Pod
```bash
kubectl exec -it -n migraine-forecast deployment/migraine-forecast-cron -- /bin/bash
```

### Once Inside a Pod
```bash
ls -la                          # List files
python manage.py shell          # Django shell
sqlite3 db.sqlite3              # Access database
cat /var/log/cron.log           # Cron logs (cron pod only)
crontab -l                      # List cron jobs (cron pod only)
env                             # Check environment variables
```

## Run Commands Without Shell

### Django Shell
```bash
kubectl exec -it -n migraine-forecast deployment/migraine-forecast-web -- python manage.py shell
```

### Run Migrations
```bash
kubectl exec -n migraine-forecast deployment/migraine-forecast-web -- python manage.py migrate
```

### Create Superuser
```bash
kubectl exec -it -n migraine-forecast deployment/migraine-forecast-web -- python manage.py createsuperuser
```

### Check Database
```bash
kubectl exec -n migraine-forecast deployment/migraine-forecast-web -- ls -lh db.sqlite3
```

## Check Database

### Access SQLite
```bash
kubectl exec -it -n migraine-forecast deployment/migraine-forecast-web -- sqlite3 db.sqlite3
```

### Inside sqlite3
```sql
.tables                                   -- List tables
.schema users_customuser                  -- Show table structure
SELECT * FROM users_customuser;           -- Query data
.quit                                     -- Exit
```

### Check Database Integrity
```bash
kubectl exec -n migraine-forecast deployment/migraine-forecast-web -- sqlite3 db.sqlite3 "PRAGMA integrity_check;"
```

## Check Backups

### List Backups on Pi
```bash
ls -lh ~/migraine/backups/
```

### List Backups from Pod
```bash
kubectl exec -n migraine-forecast deployment/migraine-forecast-cron -- ls -lh /backups/
```

## Restart Pods

### Restart Web
```bash
kubectl rollout restart deployment/migraine-forecast-web -n migraine-forecast
```

### Restart Cron
```bash
kubectl rollout restart deployment/migraine-forecast-cron -n migraine-forecast
```

### Delete Specific Pod (Auto-recreates)
```bash
kubectl delete pod <pod-name> -n migraine-forecast
```

## Common Problems

### Pod Not Starting
```bash
kubectl describe pod -n migraine-forecast -l component=web
```
Look for: `ImagePullBackOff`, `CrashLoopBackOff`, `Pending`

### Database Locked
```bash
# Check for duplicate pods
kubectl get pods -n migraine-forecast

# Delete old deployment if exists
kubectl delete deployment migraine-forecast -n migraine-forecast
```

### Service Not Accessible
```bash
# Check service
kubectl get svc -n migraine-forecast

# Check endpoints
kubectl get endpoints -n migraine-forecast

# Test from Pi
curl http://localhost:30889
```

### Cron Jobs Not Running
```bash
# Check logs
kubectl logs -n migraine-forecast -l component=cron --tail=100

# Check cron log file
kubectl exec -it -n migraine-forecast deployment/migraine-forecast-cron -- cat /var/log/cron.log
```

### Out of Disk Space
```bash
# Check disk
df -h

# Check Docker disk
docker system df

# Clean Docker images
docker image prune -a -f
```

## Rollback

### View History
```bash
kubectl rollout history deployment/migraine-forecast-web -n migraine-forecast
```

### Rollback to Previous
```bash
kubectl rollout undo deployment/migraine-forecast-web -n migraine-forecast
```

## Nuclear Option (Delete Everything)

⚠️ **WARNING**: This deletes all pods, deployments, services, jobs, secrets!
✅ Database and backups on disk are NOT deleted (they're safe).

```bash
# Delete everything
kubectl delete namespace migraine-forecast

# Redeploy
kubectl apply -k k8s/
```

## Useful Shortcuts

Add to `~/.bashrc`:

```bash
alias kgp='kubectl get pods -n migraine-forecast'
alias web-logs='kubectl logs -n migraine-forecast -l component=web -f'
alias cron-logs='kubectl logs -n migraine-forecast -l component=cron -f'
alias web-shell='kubectl exec -it -n migraine-forecast deployment/migraine-forecast-web -- /bin/bash'
alias cron-shell='kubectl exec -it -n migraine-forecast deployment/migraine-forecast-cron -- /bin/bash'
```

Reload:
```bash
source ~/.bashrc
```

Now you can use:
```bash
kgp           # Get pods
web-logs      # Follow web logs
web-shell     # Get shell in web pod
```

