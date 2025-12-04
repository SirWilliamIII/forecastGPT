#!/bin/bash
# Railway Database Setup Script

echo "Railway PostgreSQL Setup"
echo "========================"
echo ""
echo "1. Get your PostgreSQL connection URL from Railway:"
echo "   - Railway Dashboard → PostgreSQL service → Connect tab"
echo "   - Copy the 'Postgres Connection URL'"
echo ""
read -p "Paste your Railway PostgreSQL URL: " DB_URL
echo ""

echo "Connecting to Railway PostgreSQL..."
echo ""

# Enable pgvector extension
echo "Enabling pgvector extension..."
psql "$DB_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"

if [ $? -eq 0 ]; then
    echo "✓ pgvector extension enabled"
else
    echo "✗ Failed to enable pgvector"
    exit 1
fi

# Check if init.sql exists
if [ -f "db/init.sql" ]; then
    echo ""
    echo "Found db/init.sql schema file."
    read -p "Do you want to run the schema now? (y/n): " run_schema

    if [ "$run_schema" = "y" ]; then
        echo "Running database schema..."
        psql "$DB_URL" -f db/init.sql

        if [ $? -eq 0 ]; then
            echo "✓ Database schema created successfully"
        else
            echo "✗ Failed to create schema"
            exit 1
        fi
    fi
fi

echo ""
echo "✓ Railway database setup complete!"
echo ""
echo "Next steps:"
echo "1. Push your code to GitHub: git push origin main"
echo "2. Railway will automatically deploy your backend"
echo "3. Check deployment logs in Railway dashboard"
