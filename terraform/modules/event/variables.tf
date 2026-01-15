variable "rule_name" {
    description = "The name of the CloudWatch Event Rule"
    type        = string
}

variable "schedule_expression" {
    description = "The schedule expression for the CloudWatch Event Rule"
    type        = string
    default     = "cron(0 0 ? * SUN *)" # Every Sunday at midnight
}