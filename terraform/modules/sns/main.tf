# Encrypt the topic with the AWS-managed SNS key (alias/aws/sns). There is no
# customer-managed key to provision, pay for, or schedule for deletion — which
# suits the ephemeral deploy/scan/destroy lifecycle (a CMK would otherwise leave
# a 7-day pending-deletion key behind on every teardown). The AWS-managed key is
# auto-rotated by AWS and free.
resource "aws_sns_topic" "zombie_notifications" {
  name              = "ZombieHunterNotifications"
  kms_master_key_id = "alias/aws/sns"
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
