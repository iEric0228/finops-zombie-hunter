data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = abspath("${path.root}/../../../src/hunter.py")
  output_path = "${path.module}/hunter.zip"
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "this" {
  filename                       = data.archive_file.lambda_zip.output_path
  function_name                  = var.function_name
  role                           = var.iam_role_arn
  handler                        = "hunter.lambda_handler"
  timeout                        = var.timeout
  memory_size                    = var.memory_size
  runtime                        = "python3.12"
  reserved_concurrent_executions = var.reserved_concurrency
  source_code_hash               = data.archive_file.lambda_zip.output_base64sha256

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(var.env_vars, { SNS_TOPIC_ARN = var.sns_topic_arn })
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}
