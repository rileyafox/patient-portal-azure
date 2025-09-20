#!/usr/bin/env bash
set -euo pipefail

# Required: az login
RG="patient-portal-rg"
LOC="eastus"
SBNS="pp-sb-$(openssl rand -hex 3)"
SBQ="reminders"
ACSNAME="pp-acs-$(openssl rand -hex 3)"
SQLSERVER="ppsql$RANDOM"
SQLDB="patient_portal"
FUNCAPP="pp-func-$RANDOM"
STACC="ppfuncsa$RANDOM"
PLAN="pp-plan"
SWA="pp-swa-$RANDOM"

az group create -n $RG -l $LOC

# Service Bus
az servicebus namespace create -g $RG -n $SBNS --location $LOC --sku Standard
az servicebus queue create -g $RG --namespace-name $SBNS -n $SBQ
SB_CONNSTR=$(az servicebus namespace authorization-rule keys list -g $RG --namespace-name $SBNS --name RootManageSharedAccessKey --query primaryConnectionString -o tsv)

# Communication Services
az communication create -g $RG -n $ACSNAME --data-location "United States" -l $LOC
ACS_CONNSTR=$(az communication connection-string show -g $RG -n $ACSNAME --query connectionString -o tsv)

# SQL (password auth for quickstart; switch to AAD MI in prod)
SQLPASS="$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c16)"
az sql server create -g $RG -n $SQLSERVER -l $LOC -u sqladmin -p $SQLPASS
az sql db create -g $RG -s $SQLSERVER -n $SQLDB --service-objective S0
az sql server firewall-rule create -g $RG -s $SQLSERVER -n AllowAllAzureIPs --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0

echo "Run the SQL script infra/create_sql_tables.sql in the DB (Azure Portal -> SQL Database -> Query editor)."

# Storage for Functions
az storage account create -g $RG -n $STACC -l $LOC --sku Standard_LRS

# Consumption Linux Function App (Python)
az functionapp plan create -g $RG -n $PLAN --location $LOC --sku Y1 --is-linux
az functionapp create -g $RG -n $FUNCAPP --storage-account $STACC --plan $PLAN --runtime python --functions-version 4

# App settings
az functionapp config appsettings set -g $RG -n $FUNCAPP --settings \    "SB_CONNSTR=$SB_CONNSTR" \    "SB_QUEUE=$SBQ" \    "ACS_CONNSTR=$ACS_CONNSTR" \    "FROM_PHONE=" \    "FROM_EMAIL=" \    "SQL_CXN=Driver={ODBC Driver 18 for SQL Server};Server=tcp:$SQLSERVER.database.windows.net,1433;Database=$SQLDB;Uid=sqladmin;Pwd=$SQLPASS;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

echo "To deploy the Functions code:"
echo "  cd api && func azure functionapp publish $FUNCAPP"

# Static Web App (builds in GitHub ideally; for quickstart we create placeholder)
az staticwebapp create -n $SWA -g $RG -s . -l $LOC --login-with-github false || true

echo "For production: connect SWA to your GitHub repo for CI/CD."
echo "Remember to purchase/assign ACS phone number and verify ACS email domain before sending."
