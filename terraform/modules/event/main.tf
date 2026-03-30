resource "aws_cloudwatch_event_rule" "weekly_cleanup" {
  name                = var.rule_name
  description         = "Triggers the FinOps Zombie Hunter Lambda on schedule"
  schedule_expression = var.schedule_expression
  tags                = var.common_tags
}

resource "aws_cloudwatch_event_target" "trigger_lambda" {
  rule      = aws_cloudwatch_event_rule.weekly_cleanup.name
  target_id = "FinOps-Zombie-Hunter-Target"
  arn       = var.lambda_function_arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_cleanup.arn
}
