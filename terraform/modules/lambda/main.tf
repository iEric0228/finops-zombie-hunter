# ---LAMBDA CONFIGURATION
# 1. Package the Python code into a ZIP
data "archive_file" "lambda_zip" {
    type = "zip"
    source_file = "${path.root}/src/hunter.py"
    output_path = "${path.module}hunter.zip"
}

# 2. Create the Lambda Function 
resource "aws_lambda_function" "Finops_Zombie_Hunter" {
    filename         = data.archive_file.lambda_zip.output_path
    function_name    = var.function_name
    role             = var.i_am_role_arn
    handler          = "hunter.lambda_handler"
    runtime          = "python3.8"
    source_code_hash = data.archive_file.lambda_zip.output_base64sha256

    tags = var.common_tags

    environment {
        variables = var.env_vars
    }
}