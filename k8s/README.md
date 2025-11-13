# Kubernetes Deployment Guide for Migraine Forecast

This guide will help you deploy the Migraine Forecast application to Kubernetes on your Raspberry Pi.

---

## 🚀 Quick Start (5 Minutes)

```bash
# 1. Install k3s
curl -sfL https://get.k3s.io | sh -

# 2. Configure kubectl
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
chmod 600 ~/.kube/config

# 3. Set KUBECONFIG environment variable
export KUBECONFIG=~/.kube/config
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc

# 4. Verify installation
kubectl get nodes

# 5. Deploy the app (GitHub Actions will handle secrets)
cd ~/migraine_forecast
kubectl apply -k k8s/

# 6. Check status
kubectl get pods -n migraine-forecast

# 7. Access your app at http://your-pi-ip:30889
```

**That's it!** Your app is now running on Kubernetes.

For automatic deployments, just push to the `main` branch and GitHub Actions will handle everything.

---

## Prerequisites

- Raspberry Pi (tested on Pi 5) with Raspberry Pi OS
- At least 2GB RAM available
- SSH access to your Pi
- GitHub self-hosted runner configured on your Pi

## Table of Contents

1. [Quick Start](#-quick-start-5-minutes) ⬆️
2. [Install k3s (Lightweight Kubernetes)](#1-install-k3s)
3. [Configure kubectl](#2-configure-kubectl)
4. [Prepare Secrets](#3-prepare-secrets)
5. [Deploy the Application](#4-deploy-the-application)
6. [Verify Deployment](#5-verify-deployment)
7. [Common Commands](#6-common-commands)
8. [Troubleshooting](#7-troubleshooting)
9. [Migration from Docker](#8-migration-from-docker)

---

## 1. Install k3s

k3s is a lightweight Kubernetes distribution perfect for Raspberry Pi.

```bash
# SSH to your Raspberry Pi
ssh alexandros@your-pi-ip

# Install k3s (takes ~2 minutes)
curl -sfL https://get.k3s.io | sh -

# Verify installation
sudo k3s kubectl get nodes

# You should see:
# NAME      STATUS   ROLES                  AGE   VERSION
# your-pi   Ready    control-plane,master   1m    v1.28.x+k3s1
```

## 2. Configure kubectl

Set up kubectl to work without sudo:

```bash
# Create .kube directory
mkdir -p ~/.kube

# Copy k3s config
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config

# Set permissions
chmod 600 ~/.kube/config

# Set KUBECONFIG environment variable (IMPORTANT!)
export KUBECONFIG=~/.kube/config
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc

# Test kubectl (without sudo)
kubectl get nodes

# Create alias for convenience (optional)
echo "alias k='kubectl'" >> ~/.bashrc
source ~/.bashrc
```

## 3. Prepare Secrets

**Good news!** Secrets are automatically created from your GitHub secrets during deployment. You don't need to store them locally on the Pi.

The GitHub Actions workflow will create the Kubernetes secrets from:
- `secrets.SENTRY_DSN`
- `secrets.DOCKERHUB_TOKEN`
- `vars.SENTRY_ENABLED`
- `vars.SENTRY_ENVIRONMENT`
- `vars.SENTRY_TRACES_SAMPLE_RATE`
- `vars.SENTRY_PROFILES_SAMPLE_RATE`
- `vars.DOCKERHUB_USERNAME`

**For manual deployment** (without GitHub Actions), you can create secrets manually:

```bash
# Create namespace first
kubectl create namespace migraine-forecast

# Create secret
kubectl create secret generic migraine-secrets \
  --from-literal=SENTRY_DSN="your-sentry-dsn" \
  --from-literal=DOCKERHUB_TOKEN="your-dockerhub-token" \
  --namespace=migraine-forecast

# Create ConfigMap
kubectl create configmap migraine-config \
  --from-literal=DJANGO_DEBUG="False" \
  --from-literal=SENTRY_ENABLED="true" \
  --from-literal=SENTRY_ENVIRONMENT="production" \
  --from-literal=SENTRY_TRACES_SAMPLE_RATE="1.0" \
  --from-literal=SENTRY_PROFILES_SAMPLE_RATE="1.0" \
  --from-literal=DOCKERHUB_USERNAME="alexandrosm77" \
  --namespace=migraine-forecast
```

## 4. Deploy the Application

### Option A: Deploy Everything at Once (Recommended)

```bash
cd ~/migraine_forecast

# 1. Create secrets and config (see step 3 above for manual creation)
# OR let GitHub Actions create them automatically

# 2. Apply all manifests
kubectl apply -k k8s/

# This will create:
# - Namespace: migraine-forecast
# - PersistentVolumes and PersistentVolumeClaims
# - Deployment (your app)
# - Service (exposes port 30889)
# - CronJob (daily backups)
```

### Option B: Deploy Step-by-Step (For Manual Setup)

```bash
cd ~/migraine_forecast

# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Create storage
kubectl apply -f k8s/persistent-volume.yaml

# 3. Create secrets and config (see step 3 above)
kubectl create secret generic migraine-secrets ...
kubectl create configmap migraine-config ...

# 4. Run initial migration (if you have existing database)
kubectl apply -f k8s/migration-job.yaml
kubectl wait --for=condition=complete --timeout=300s job/migraine-migration -n migraine-forecast

# 5. Deploy the application
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# 6. Set up automated backups
kubectl apply -f k8s/backup-cronjob.yaml
```

### Option C: Let GitHub Actions Do Everything (Easiest)

Just push to the `main` branch and GitHub Actions will:
1. Build and test the Docker image
2. Create/update secrets from GitHub secrets
3. Backup the database
4. Run migrations
5. Deploy the application

No manual steps needed!

## 5. Verify Deployment

```bash
# Check all resources
kubectl get all -n migraine-forecast

# Check pods (should show 1/1 RUNNING)
kubectl get pods -n migraine-forecast

# Check service (note the NodePort)
kubectl get svc -n migraine-forecast

# View logs
kubectl logs -n migraine-forecast -l app=migraine-forecast

# Follow logs in real-time
kubectl logs -n migraine-forecast -l app=migraine-forecast -f

# Check if cron is running inside the pod
kubectl exec -n migraine-forecast -it deployment/migraine-forecast -- pgrep cron
```

### Access Your Application

Your app will be available at:
- **http://your-pi-ip:30889**

For example: `http://192.168.0.11:30889`

## 6. Common Commands

### Viewing Resources

```bash
# Get all resources in the namespace
kubectl get all -n migraine-forecast

# Get pods with more details
kubectl get pods -n migraine-forecast -o wide

# Describe a pod (useful for troubleshooting)
kubectl describe pod <pod-name> -n migraine-forecast

# View logs
kubectl logs -n migraine-forecast -l app=migraine-forecast --tail=50

# View logs from previous crashed container
kubectl logs -n migraine-forecast -l app=migraine-forecast --previous
```

### Managing the Application

```bash
# Restart the deployment
kubectl rollout restart deployment/migraine-forecast -n migraine-forecast

# Scale to 0 replicas (stop the app)
kubectl scale deployment/migraine-forecast --replicas=0 -n migraine-forecast

# Scale back to 1 replica (start the app)
kubectl scale deployment/migraine-forecast --replicas=1 -n migraine-forecast

# Update to latest image
kubectl set image deployment/migraine-forecast \
  migraine-forecast=alexandrosm77/migraine_forecast:latest \
  -n migraine-forecast

# Check rollout status
kubectl rollout status deployment/migraine-forecast -n migraine-forecast

# Rollback to previous version
kubectl rollout undo deployment/migraine-forecast -n migraine-forecast
```

### Database Operations

```bash
# Run migrations manually
kubectl delete job migraine-migration -n migraine-forecast --ignore-not-found=true
kubectl apply -f k8s/migration-job.yaml
kubectl logs -n migraine-forecast job/migraine-migration -f

# Create a manual backup
kubectl create job --from=cronjob/migraine-db-backup manual-backup-$(date +%s) -n migraine-forecast

# Access the database directly
kubectl exec -n migraine-forecast -it deployment/migraine-forecast -- python manage.py dbshell

# Run Django management commands
kubectl exec -n migraine-forecast -it deployment/migraine-forecast -- python manage.py createsuperuser
kubectl exec -n migraine-forecast -it deployment/migraine-forecast -- python manage.py collectstatic --noinput
```

### Debugging

```bash
# Get a shell inside the pod
kubectl exec -n migraine-forecast -it deployment/migraine-forecast -- /bin/bash

# Check events (useful for troubleshooting)
kubectl get events -n migraine-forecast --sort-by='.lastTimestamp'

# Check resource usage
kubectl top pods -n migraine-forecast
kubectl top nodes
```

## 7. Troubleshooting

### Pod is not starting

```bash
# Check pod status
kubectl get pods -n migraine-forecast

# Describe the pod to see events
kubectl describe pod <pod-name> -n migraine-forecast

# Common issues:
# - ImagePullBackOff: Docker Hub credentials issue
# - CrashLoopBackOff: Application is crashing, check logs
# - Pending: Storage or resource issues
```

### Cannot access the application

```bash
# Check service
kubectl get svc -n migraine-forecast

# Verify the NodePort (should be 30889)
# Access via: http://<pi-ip>:30889

# Check if pod is ready
kubectl get pods -n migraine-forecast

# Check firewall (if needed)
sudo ufw allow 30889/tcp
```

### Database issues

```bash
# Check if PVC is bound
kubectl get pvc -n migraine-forecast

# Check PV
kubectl get pv

# Verify the database file exists on the host
ls -lh /home/alexandros/migraine/db.sqlite3

# Check backups
ls -lh /home/alexandros/migraine/backups/
```

### Cron jobs not running

```bash
# Check CronJob
kubectl get cronjobs -n migraine-forecast

# Check recent jobs
kubectl get jobs -n migraine-forecast

# View CronJob logs
kubectl logs -n migraine-forecast job/<job-name>

# Manually trigger a CronJob
kubectl create job --from=cronjob/migraine-db-backup test-backup -n migraine-forecast
```

## 8. Migration from Docker

If you're migrating from the existing Docker setup:

### Before Migration

```bash
# 1. Stop the Docker container
docker stop migraine

# 2. Your database is already at /home/alexandros/migraine/db.sqlite3
# This will be automatically used by Kubernetes (same path)

# 3. Backup your database (just in case)
cp /home/alexandros/migraine/db.sqlite3 ~/db.sqlite3.pre-k8s-backup
```

### After Kubernetes Deployment

```bash
# 1. Verify the app is running
kubectl get pods -n migraine-forecast

# 2. Access the app at http://your-pi-ip:30889

# 3. If everything works, remove the old Docker container
docker rm migraine

# 4. (Optional) Clean up Docker images
docker image prune -a
```

### Rollback to Docker (if needed)

```bash
# 1. Delete Kubernetes deployment
kubectl delete -k k8s/

# 2. Restore database backup (if needed)
cp ~/db.sqlite3.pre-k8s-backup /home/alexandros/migraine/db.sqlite3

# 3. Start Docker container again
# (Use the commands from the old workflow)
```

---

## GitHub Actions Integration

The GitHub Actions workflow will automatically:
1. Build and push Docker image
2. Run tests
3. Create database backup
4. Run migrations
5. Deploy to Kubernetes
6. Clean up old jobs

**Branches:**
- `dev` branch → Docker deployment (old workflow)
- `main` branch → Kubernetes deployment (new workflow)

---

## Useful Resources

- [k3s Documentation](https://docs.k3s.io/)
- [Kubernetes Basics](https://kubernetes.io/docs/tutorials/kubernetes-basics/)
- [kubectl Cheat Sheet](https://kubernetes.io/docs/reference/kubectl/cheatsheet/)

---

## Next Steps

1. Set up monitoring (optional): Install Prometheus + Grafana
2. Set up Ingress (optional): Use Traefik (included with k3s) for better routing
3. Set up cert-manager (optional): For automatic HTTPS certificates
4. Explore Helm charts: Package your app as a Helm chart for easier management

