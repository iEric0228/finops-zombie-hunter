output "lambda_function_name" {
  description = "The name of the Lambda function"
  value       = module.lambda.lambda_function_name
}

output "lambda_function_arn" {
  description = "The ARN of the Lambda function"
  value       = module.lambda.lambda_function_arn
}

output "report_bucket_name" {
  description = "The S3 bucket that stores scan reports"
  value       = module.report_bucket.bucket_name
}