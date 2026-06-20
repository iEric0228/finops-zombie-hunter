output "state_bucket" {
  description = "Name of the created remote-state S3 bucket"
  value       = aws_s3_bucket.state.bucket
}

output "lock_table" {
  description = "Name of the created state-lock DynamoDB table"
  value       = aws_dynamodb_table.lock.name
}
