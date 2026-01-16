terraform {
  backend "s3" {
    bucket         = "finops-zombie-hunter"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-lock-finops"
    encrypt        = true
  }
}