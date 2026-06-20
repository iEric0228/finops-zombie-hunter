variable "name_prefix" {
  description = "Prefix for the globally-unique report bucket name"
  type        = string
  default     = "finops-zombie-hunter"
}

variable "environment" {
  description = "Environment name, included in the bucket name"
  type        = string
}

variable "retention_days" {
  description = "Days to retain report objects before lifecycle expiration"
  type        = number
  default     = 90

  validation {
    condition     = var.retention_days >= 1
    error_message = "Retention must be at least 1 day."
  }
}

variable "force_destroy" {
  description = "Allow `terraform destroy` to delete the bucket even with reports in it. Required for the ephemeral scan-once (deploy->scan->destroy) flow; reports are disposable."
  type        = bool
  default     = true
}
