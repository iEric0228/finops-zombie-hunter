resource "aws_kms_key" "sns" {
  description             = "Customer managed key for SNS topic encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "sns" {
  name          = "alias/zombie-hunter-sns"
  target_key_id = aws_kms_key.sns.key_id
}

resource "aws_sns_topic" "zombie_notifications" {
  name              = "ZombieHunterNotifications"
  kms_master_key_id = aws_kms_key.sns.arn
}

# Only subscribe when an email is provided. With no email the topic still
# exists and the Lambda still publishes; reports remain available via S3 and
# the workflow run summary.
resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.zombie_notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

variable "notification_email" {
  description = "The email address to receive SNS notifications (empty = no subscription)"
  type        = string
  default     = ""
}

output "topic_arn" {
  description = "ARN of the SNS notification topic"
  value       = aws_sns_topic.zombie_notifications.arn
}
