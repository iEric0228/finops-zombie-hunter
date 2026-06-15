# FinOps Zombie Hunter

[![Deploy Status](https://github.com/iEric0228/finops-zombie-hunter/actions/workflows/deploy.yml/badge.svg)](https://github.com/iEric0228/finops-zombie-hunter/actions/workflows/deploy.yml)
[![Lint Status](https://github.com/iEric0228/finops-zombie-hunter/actions/workflows/lint.yml/badge.svg)](https://github.com/iEric0228/finops-zombie-hunter/actions/workflows/lint.yml)
[![AWS](https://img.shields.io/badge/AWS-FF9900?style=flat-square&logo=amazon-aws&logoColor=white)](https://aws.amazon.com/)
[![Terraform](https://img.shields.io/badge/Terraform-623CE4?style=flat-square&logo=terraform&logoColor=white)](https://terraform.io/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org/)

Automated AWS cost-optimization engine that identifies zombie (unused) resources across all regions, **safely deletes the low-risk ones**, persists a report to S3, and sends a savings summary via SNS.

> **Safety first:** deletion is **off by default** (`dry_run = true`). Only unattached EBS volumes and unassociated Elastic IPs are ever deleted — and only when they are older than a configurable threshold and not tagged `keep`/`DoNotDelete`. RDS instances and NAT gateways are **report-only** and are never deleted automatically. See [§5 Destroy & Safety Model](#5-destroy--safety-model).

---

## 1. The Problem

Cloud waste costs companies billions annually. Developers delete EC2 instances but forget associated EBS volumes, NAT Gateways, RDS databases, and Elastic IPs — "zombie" resources that silently accumulate charges every month.

---

## 2. Architecture

```
+---------------------------------------------------------------+
|                  CI/CD Layer (GitHub Actions)                   |
|  Workflows: Deploy, Scan-Once, Lint                            |
|  Features: OIDC auth, concurrency control, security scanning   |
+---------------------------------------------------------------+
                            |
                            v
+---------------------------------------------------------------+
|             Infrastructure Layer (Terraform)                    |
|  +--------+  +--------+  +--------+  +---------+              |
|  |  IAM   |->| Lambda |->|  SNS   |->|  Event  |              |
|  | Module |  | Module |  | Module |  | Module  |              |
|  +--------+  +--------+  +--------+  +---------+              |
|  Least-priv  Python 3.12 KMS-encrypt EventBridge              |
|  scoped ARNs 256MB/300s  email sub   cron schedule             |
+---------------------------------------------------------------+
                            |
                            v
+---------------------------------------------------------------+
|              Runtime Layer (Lambda + CloudWatch)                |
|                                                                |
|  For each AWS region:                                          |
|    1. EBS: Unattached volumes (status=available)  [deletable]  |
|    2. RDS: Zero connections over 7 days           [report-only]|
|    3. NAT GW: Zero bytes out over 7 days          [report-only]|
|    4. EIP: Unassociated Elastic IPs               [deletable]  |
|                                                                |
|  Deletable + DRY_RUN=false + older than MIN_AGE_DAYS           |
|  + no keep tag  ->  delete                                     |
|                                                                |
|  -> Aggregated report -> S3 (JSON + Markdown) -> SNS summary   |
+---------------------------------------------------------------+
```

### Repository Layout

```
finops-zombie-hunter/
├── src/
│   ├── hunter.py                     # Core Lambda function (zombie detection)
│   └── requirements.txt              # Python dependencies (boto3)
├── terraform/
│   ├── environments/
│   │   └── dev/                      # Root module (orchestrates all modules)
│   │       ├── main.tf               # Module composition & wiring
│   │       ├── variables.tf          # Configurable inputs with validation
│   │       ├── output.tf             # Exports Lambda name and ARN
│   │       ├── backend.tf            # S3 + DynamoDB remote state
│   │       └── terraform.tfvars.example
│   └── modules/
│       ├── IAM/                      # Lambda execution role (least-privilege + gated delete)
│       ├── lambda/                   # Lambda function + CloudWatch Log Group
│       ├── sns/                      # SNS topic with KMS encryption
│       ├── report-bucket/           # Private, versioned, TLS-only S3 report store
│       └── event/                    # EventBridge scheduled trigger
├── .github/
│   └── workflows/
│       ├── deploy.yml                # Deploy pipeline (plan/apply/destroy)
│       ├── scan-once.yml             # Ephemeral: deploy, scan, destroy
│       └── lint.yml                  # Terraform + Python linting & security
└── share/                            # Architecture diagrams
```

---

## 3. Key Components

- **Lambda Function (`src/hunter.py`):** Scans all AWS regions for zombie EBS volumes, idle RDS instances, unused NAT Gateways, and unattached EIPs using CloudWatch metrics. Deletes the two safe-to-remove types (EBS, EIP) when `DRY_RUN=false`, subject to an age threshold and a `keep` tag exclusion. Aggregates everything into a structured report.
- **IAM Module:** Least-privilege role with separate policies for read-only scanning, SNS publishing (scoped to topic ARN), report writing (scoped to the bucket's `reports/` prefix), and logging. Delete permissions are attached **only** when `enable_destroy` is set (derived from `!dry_run`).
- **Lambda Module:** Python 3.12 runtime, 256MB memory, 300s timeout, reserved concurrency of 1, managed CloudWatch Log Group with 14-day retention.
- **SNS Module:** KMS-encrypted topic with email subscription for scan result notifications.
- **Report Bucket Module:** Private S3 bucket (public access blocked, versioned, SSE-S3 encrypted, TLS-only via bucket policy) storing each run's JSON + Markdown report, with a lifecycle rule that expires old reports.
- **Event Module:** EventBridge rule using configurable schedule expression (default: weekly Sunday midnight).

---

## 4. Data Flow

### Zombie Detection Flow

```
1. EventBridge triggers Lambda on schedule (weekly by default)
2. Lambda lists all enabled AWS regions
3. For each region, Lambda checks:
   a. EBS volumes with status "available" (unattached)      [deletable]
   b. RDS instances with 0 average connections over 7 days  [report-only]
   c. NAT Gateways with 0 bytes out over 7 days             [report-only]
   d. Elastic IPs without an AssociationId (unassociated)   [deletable]
4. For each deletable resource, if DRY_RUN=false AND it is older than
   MIN_AGE_DAYS AND it has no keep/DoNotDelete tag -> delete it;
   otherwise record it as "would_delete" (dry-run) or "skipped"
5. Results aggregated into a report (per-resource action + savings)
6. Report persisted to S3 as JSON + Markdown
7. Summary published to SNS (email notification) with the report link
8. Summary returned for CI/CD logging
```

### CI/CD Workflows

| Workflow | Trigger | Description |
|----------|---------|-------------|
| `deploy.yml` | Push to main (plan only), manual dispatch | Plan/Apply/Destroy with OIDC auth |
| `scan-once.yml` | Manual dispatch | Deploy infra, invoke scan, destroy (ephemeral) |
| `lint.yml` | Push/PR to main | Terraform fmt/validate, Trivy IaC scan, Black, Flake8, Pylint, Bandit |

---

## 5. Destroy & Safety Model

Deletion is deliberately conservative — the tool is designed so an accidental or
misconfigured run cannot cause data loss or an outage.

| Resource | Eligible for auto-delete? | Why |
|----------|---------------------------|-----|
| Unattached EBS volume | ✅ Yes (guarded) | Low blast radius; only the detached volume is removed |
| Unassociated Elastic IP | ✅ Yes (guarded) | No data; just releases the address |
| Idle RDS instance | ❌ Report-only | Deleting a database is irreversible data loss |
| Idle NAT Gateway | ❌ Report-only | Deleting one can sever connectivity for a whole subnet |

A deletable resource is removed **only when all** of the following hold:

1. `DRY_RUN=false` (default is `true` — nothing is deleted), **and**
2. the resource is older than `MIN_AGE_DAYS` (default 7), **and**
3. it carries no `keep` / `DoNotDelete` tag.

Defense in depth: when `dry_run = true`, the IAM role has **no delete permissions
at all** (`ec2:DeleteVolume` / `ec2:ReleaseAddress` are attached only when
`enable_destroy` is set). So even a code change cannot delete anything from a
dry-run deployment. Every run writes a full report listing each resource and the
action taken (`deleted` / `would_delete` / `report_only` / `skipped` with reason).

## 6. Security

| Feature | Implementation |
|---------|---------------|
| **Authentication** | GitHub OIDC -> AWS STS (no static credentials) |
| **IAM Scoping** | Read-only scanning; SNS publish scoped to topic ARN; report writes scoped to bucket `reports/` prefix; logs scoped to log group ARN |
| **Gated deletion** | Delete permissions attached only when `enable_destroy = !dry_run`; runtime age + tag guards |
| **Encryption** | SNS topic uses a customer-managed KMS key (auto-rotation); report bucket uses SSE-S3 |
| **Report bucket** | Public access blocked, versioned, TLS-only (bucket policy denies non-HTTPS), lifecycle expiry |
| **Dry-Run** | Default mode prevents any resource deletion |
| **Concurrency** | `reserved_concurrent_executions = 1` prevents parallel runs |
| **CI/CD** | Push to main only plans (no auto-apply), manual approval required for apply |
| **Scanning** | Trivy (IaC), Bandit (Python security), Flake8, Pylint, **pytest** in CI pipeline |
| **State** | S3 backend with encryption, versioning, DynamoDB locking |

---

## 7. Tech Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Compute | AWS Lambda | - | Serverless zombie detection |
| Runtime | Python | 3.12 | Boto3 SDK for AWS API calls |
| IaC | Terraform | >= 1.5 | Infrastructure provisioning |
| Cloud | AWS (Lambda, SNS, EventBridge, CloudWatch, S3) | Provider ~> 5.0 | Managed services |
| Notifications | SNS + KMS | - | Encrypted email alerts |
| Reporting | S3 | - | Versioned JSON + Markdown report store |
| Scheduling | EventBridge | - | Cron-based Lambda triggers |
| CI/CD | GitHub Actions | - | OIDC-authenticated pipelines |
| Security | Trivy, Bandit, Flake8, Pylint, Black, pytest | - | Shift-left security, linting & tests |

---

## 8. Quickstart

### Prerequisites

- AWS account with permissions for Lambda, IAM, SNS, EventBridge, CloudWatch, EC2, RDS, S3
- Terraform >= 1.5
- Python 3.12+
- GitHub Actions OIDC role configured for your repository

### Setup

1. Fork + clone this repo
2. Create GitHub Actions secrets:
   - `AWS_ROLE_ARN`: `arn:aws:iam::<ACCOUNT_ID>:role/<OIDC_ROLE>`
   - `NOTIFICATION_EMAIL`: Email for scan notifications
3. Copy and customize variables:
   ```bash
   cp terraform/environments/dev/terraform.tfvars.example terraform/environments/dev/terraform.tfvars
   ```

### Run via CI/CD (recommended)

- **Plan only:** Push to `main` (automatic)
- **Apply:** Actions > `Terraform Deploy` > Run workflow > action: `apply`
- **Scan once:** Actions > `Scan Once` > Run workflow (deploys, scans, destroys automatically)
- **Destroy:** Actions > `Terraform Deploy` > Run workflow > action: `destroy`

### Run locally

```bash
cd terraform/environments/dev
terraform init
terraform plan
terraform apply   # Only when ready
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `aws_region` | `us-east-1` | AWS region |
| `environment` | `dev` | Environment name (dev/staging/prod) |
| `notification_email` | - | Email for SNS notifications (required) |
| `schedule_expression` | `cron(0 0 ? * SUN *)` | EventBridge schedule |
| `dry_run` | `true` | Dry-run mode. `true` = detect/report only; `false` = also delete eligible EBS/EIP and attach delete IAM |
| `min_age_days` | `7` | Minimum age before an unattached resource is eligible for deletion |
| `report_retention_days` | `90` | Days to keep reports in S3 before lifecycle expiry |
| `lambda_timeout` | `300` | Lambda timeout in seconds |
| `lambda_memory_size` | `256` | Lambda memory in MB |

> **To actually delete resources:** set `dry_run = false` in your tfvars and apply. This both enables the deletion code path and attaches the scoped delete permissions to the role. Start with a high `min_age_days` and review a dry-run report first.

---

## 9. Sample Output

The Lambda returns (and SNS emails) this summary. The full per-resource report
— including the `action` taken for each resource — is written to S3 as JSON and
Markdown.

```json
{
  "timestamp": "2025-01-15T00:00:00+00:00",
  "dry_run": true,
  "min_age_days": 7,
  "regions_scanned": 17,
  "zombies_found": 20,
  "deleted": 0,
  "would_delete": 17,
  "report_only": 3,
  "skipped": 0,
  "realized_monthly_savings": "$0.00",
  "potential_monthly_savings": "$230.00",
  "savings_by_type": {
    "EBS": "$48.00",
    "RDS": "$100.00",
    "NAT_GW": "$64.00",
    "Elastic_IP": "$18.00"
  },
  "errors": []
}
```

When run with `dry_run = false`, eligible EBS/EIP resources move from
`would_delete` to `deleted`, and `realized_monthly_savings` reflects what was
actually removed.

---

## 10. Troubleshooting

### Lambda timeout on large accounts

Increase `lambda_timeout` (max 900s) and `lambda_memory_size` in your tfvars. Scanning 30+ regions with many resources can take several minutes.

### SNS email not received

After first deploy, check your email for the SNS subscription confirmation. The subscription must be confirmed before notifications work.

### Terraform state lock

If a previous run was interrupted, use `terraform force-unlock <LOCK_ID>` manually. Never automate state lock deletion.

---

## 11. Key Files Reference

| File | Purpose |
|------|---------|
| `src/hunter.py` | Core Lambda - detection, guarded deletion, and report generation |
| `tests/test_hunter.py` | Unit tests for detection, deletion guards, and report aggregation |
| `terraform/environments/dev/main.tf` | Root module wiring all components |
| `terraform/environments/dev/variables.tf` | Configurable inputs with validation |
| `terraform/modules/IAM/iam.tf` | Least-privilege IAM (read, SNS, report-S3, gated delete, logging) |
| `terraform/modules/lambda/main.tf` | Lambda function + CloudWatch Log Group |
| `terraform/modules/sns/main.tf` | KMS-encrypted SNS topic + email subscription |
| `terraform/modules/report-bucket/main.tf` | Private, versioned, TLS-only S3 report store |
| `terraform/modules/event/main.tf` | EventBridge scheduled trigger |
| `.github/workflows/deploy.yml` | Deploy pipeline (plan/apply/destroy) |
| `.github/workflows/scan-once.yml` | Ephemeral deploy-scan-destroy workflow |
| `.github/workflows/lint.yml` | Terraform + Python lint, security scan, and unit tests |

---

## Author

**Eric Chiu**
Portfolio: [Deploy on Demand](https://github.com/iEric0228/cloud-resume)
LinkedIn: [Eric Chiu](https://www.linkedin.com/in/eric-chiu-a610553a3/)
GitHub: [@iEric0228](https://github.com/iEric0228)
Email: [ericchiu0228@gmail.com](mailto:ericchiu0228@gmail.com)
