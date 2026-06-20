variable "aws_region" {
  description = "Region for the state backend (must match backend.tf)"
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "S3 bucket name for Terraform remote state (must match backend.tf)"
  type        = string
  default     = "finops-zombie-hunter"
}

variable "lock_table_name" {
  description = "DynamoDB table name for state locking (must match backend.tf)"
  type        = string
  default     = "terraform-lock-finops"
}
