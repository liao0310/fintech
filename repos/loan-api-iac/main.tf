# ============================================================
# loan-api IaC — 自動核貸服務基礎設施定義
# ============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

locals {
  service_name = "loan-api"
  region       = "asia-east1"
  project_id   = "esun-fintech-prod"

  # 利率設定 (百分比)
  base_rate_vip_a    = 1.5
  base_rate_vip_b    = 2.2
  base_rate_standard = 3.8

  # 內部服務連線
  vip_svc_internal_url = "https://vip-svc-internal.asia-east1.run.app"
}

# ── Cloud Run 服務定義 ──────────────────────────────────────
resource "google_cloud_run_v2_service" "loan_api" {
  name     = local.service_name
  location = local.region
  project  = local.project_id

  template {
    containers {
      image = "asia-east1-docker.pkg.dev/${local.project_id}/app-images/loan-api:latest"

      resources {
        limits = {
          cpu    = "4"
          memory = "2Gi"
        }
      }

      # 環境變數設定
      env {
        name  = "VIP_SVC_URL"
        value = local.vip_svc_internal_url
      }
      env {
        name  = "BASE_RATE_VIP_A"
        value = tostring(local.base_rate_vip_a)
      }
      env {
        name  = "BASE_RATE_VIP_B"
        value = tostring(local.base_rate_vip_b)
      }
      env {
        name  = "BASE_RATE_STANDARD"
        value = tostring(local.base_rate_standard)
      }
      env {
env {
  name  = "CLOUDSQL_INSTANCE_CONNECTION_NAME"
  value = "${local.project_id}:asia-east1:loan-sql-instance"
}
env {
  name  = "CLOUDSQL_DATABASE_NAME"
  value = "loan_db"
}
env {
  name  = "CLOUDSQL_USER"
  value = "loan_user"
}
env {
  name  = "CLOUDSQL_PASSWORD"
  value = "${var.cloudsql_password}"
}
      env {
        name  = "SERVICE_ENV"
        value = "production"
      }
      env {
        name  = "VIP_SVC_TIMEOUT_SEC"
        value = "10"
      }
    }

    scaling {
      min_instance_count = 2
      max_instance_count = 20
    }

    # VPC 連線（內部服務通訊用）
    vpc_access {
      connector = "projects/${local.project_id}/locations/${local.region}/connectors/internal-connector"
      egress    = "PRIVATE_RANGES_ONLY"
    }
  }
}

# ── VPC 網路權限：允許 loan-api 呼叫 vip-svc ─────────────────
resource "google_cloud_run_service_iam_member" "loan_api_invoke_vip_svc" {
  project  = local.project_id
  location = local.region
  service  = "vip-svc"
  role     = "roles/run.invoker"
  member   = "serviceAccount:loan-api-sa@${local.project_id}.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "loan_api_cloudsql_client" {
  project = local.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:loan-api-sa@${local.project_id}.iam.gserviceaccount.com"
}

# ── BigQuery Table：核貸結果 ──────────────────────────────────
resource "google_sql_database_instance" "loan_sql_instance" {
  name             = "loan-sql-instance"
  database_version = "POSTGRES_14"
  region           = local.region
  project          = local.project_id

  settings {
    tier = "db-custom-2-7680"
    ip_configuration {
      private_network = "projects/${local.project_id}/global/networks/default"
    }
  }
}

resource "google_sql_database" "loan_database" {
  name     = "loan_db"
  instance = google_sql_database_instance.loan_sql_instance.name
  project  = local.project_id
}

resource "google_sql_user" "loan_user" {
  name     = "loan_user"
  instance = google_sql_database_instance.loan_sql_instance.name
  password = var.cloudsql_password
  project  = local.project_id
}

# ── 輸出值 ──────────────────────────────────────────────────
output "loan_api_url" {
  description = "loan-api Cloud Run 服務 URL"
  value       = google_cloud_run_v2_service.loan_api.uri
}

output "vip_svc_dependency_url" {
  description = "loan-api 所依賴的 vip-svc 內部連線 URL"
  value       = local.vip_svc_internal_url
}
