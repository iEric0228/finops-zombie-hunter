output "bucket_name" {
  description = "Name of the report bucket"
  value       = aws_s3_bucket.reports.id
}

output "bucket_arn" {
  description = "ARN of the report bucket"
  value       = aws_s3_bucket.reports.arn
}
