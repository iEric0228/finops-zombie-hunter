variable "rule_name" {
    description = "The name of the CloudWatch Event Rule"
    type        = string
}

variable "schedule_expression" {
    description = "The schedule expression for the CloudWatch Event Rule"
    type        = string
    default     = "cron(0 0 ? * SUN *)" # Every Sunday at midnight
}

variable "lambda_function_arn" {
    description = "The ARN of the Lambda function to trigger"
    type        = string
}

variable "lambda_function_name" {
    description = "The name of the Lambda function to trigger"
    type        = string
}

variable "common_tags" {
    description = "A map of tags to assign to the CloudWatch Event Rule and Target"
    type        = map(string)
    default     = {}
}