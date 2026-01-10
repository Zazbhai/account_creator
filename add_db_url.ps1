$envFile = ".env"
$dbUrl = "DATABASE_URL=postgresql://neondb_owner:npg_2OJ0rvhmnCVE@ep-lingering-glade-ahxz3ciz-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Append to .env file
Add-Content -Path $envFile -Value "`n$dbUrl"

Write-Host "DATABASE_URL added to .env file successfully!"
