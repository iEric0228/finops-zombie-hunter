#--- EVENTBRIDGE SCHEDULE CONFIGURATION

# 1. Rule
resource "aws_cloudwatch_event_rule" "weekly_cleanup" {
    name               = var.rule_name
    description         = "Triggers the FinOps Zombie Hunter Lambda every Sunday at midnight"
    schedule_expression = "cron(0 0 ? * SUN *)" # Every Sunday at midnight
    tags = var.common_tags
}

# 2. Target
resource "aws_cloudwatch_event_target" "trigger_lambda_on_schedule" {
    rule      = aws_cloudwatch_event_rule.weekly_cleanup.name
    target_id = "FinOps-Zombie-Hunter-Target"
    arn       = var.lambda_function_arn
    tags = var.common_tags
}

# 3. Permission for EventBridge to invoke Lambda
resource "aws_lambda_permission" "allow_cloudwatch_to_call_hunter" {
    statement_id  = "AllowExecutionFromEventBridge"
    action        = "lambda:InvokeFunction"
    function_name = var.lambda_function_name
    principal     = "events.amazonaws.com"
    source_arn    = aws_cloudwatch_event_rule.weekly_cleanup.arn
    tags = var.common_tags

}