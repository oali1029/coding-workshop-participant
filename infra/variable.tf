variable "aws_project" {
  description = "The AWS project name."
  type        = string
  default     = "coding-workshop"
}

variable "aws_bucket" {
  description = "The AWS S3 bucket name for terraform state storage."
  type        = string
  default     = "coding-workshop-us-east-1-abcd1234"
}

variable "aws_app_code" {
  description = "The AWS application unique code."
  type        = string
  default     = "abcd1234"
}

variable "aws_ds_ip" {
  description = "The AWS Directory Service ip address."
  type        = string
  default     = ""
}

variable "aws_vpc_id" {
  description = "The AWS VPC identifier."
  type        = string
  default     = null
}

variable "aws_postgres_enabled" {
  description = "Enable or disable PostgreSQL (AWS Aurora). Default: true (set to 'false' to disable it)."
  type        = bool
  default     = true

  validation {
    condition     = contains([true, false], var.aws_postgres_enabled)
    error_message = "The aws_postgres_enabled variable must be either 'true' or 'false'."
  }
}

variable "aws_postgres_host" {
  description = "PostgreSQL host for LocalStack. Default: 'host.docker.internal' (set to '172.17.0.1' on Linux)."
  type        = string
  default     = null
}

variable "aws_mongo_enabled" {
  description = "Enable or disable MongoDB (AWS DocumentDB). Default: false (set to 'true' to enable it)."
  type        = bool
  default     = false

  validation {
    condition     = contains([true, false], var.aws_mongo_enabled)
    error_message = "The aws_mongo_enabled variable must be either 'true' or 'false'."
  }
}

variable "aws_mongo_host" {
  description = "MongoDB host for LocalStack. Default: 'host.docker.internal' (set to '172.17.0.1' on Linux)."
  type        = string
  default     = null
}

variable "aws_eks_enabled" {
  description = "Enable or disable Jupyter Notebook (AWS EKS). Default: false (set to 'true' to enable it)."
  type        = bool
  default     = false

  validation {
    condition     = contains([true, false], var.aws_eks_enabled)
    error_message = "The aws_eks_enabled variable must be either 'true' or 'false'."
  }
}

variable "aws_eks_type" {
  description = "EKS nodes type. Default: SPOT."
  type        = string
  default     = "SPOT"

  validation {
    condition     = contains(["ON_DEMAND", "SPOT"], var.aws_eks_type)
    error_message = "The aws_eks_type variable must be either 'ON_DEMAND' or 'SPOT'."
  }
}

# Password for the bootstrap FACILITY_ADMIN account the backend creates on
# startup. Supplied by the deployer, never stored in this repository:
#
#   export TF_VAR_aws_bootstrap_admin_password='<chosen-password>'
#
# Leaving it empty is supported and safe. The Lambda module filters out empty
# environment variables, so the backend simply sees the variable as unset,
# logs a warning, and skips creating the administrator account.
variable "aws_bootstrap_admin_password" {
  description = "Bootstrap FACILITY_ADMIN password. Leave empty to skip creating the account."
  type        = string
  default     = ""
  sensitive   = true
}
