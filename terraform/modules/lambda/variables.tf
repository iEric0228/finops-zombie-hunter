variable "function_name" {
    description = "The name of the Lambda function"
    type        = string

}
    
variable "i_am_role_arn" {
    description = "The ARN of the IAM role that the Lambda function will assume"
    type        = string
}

variable "env_vars" {
    description = "Environment variables for the Lambda function"
    type        = map(string)
    default     = {}
}

variable " common_tags" {
    description = "A map of tags to assign to the Lambda function"
    type        = map(string)
    default     = {}
}