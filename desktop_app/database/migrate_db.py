import sys
import os
# Add the desktop_app directory to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from database.session import SQLALCHEMY_DATABASE_URL

def migrate():
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    
    print("Connecting to database for migration...")
    with engine.connect() as conn:
        # 1. Update Routine times to proper TIME type
        print("Upgrading 'routines' table columns to native TIME...")
        conn.execute(text("""
            ALTER TABLE routines 
            ALTER COLUMN start_time TYPE TIME USING start_time::TIME,
            ALTER COLUMN end_time TYPE TIME USING end_time::TIME;
        """))
        
        # 2. Update AttendanceRecord timestamp to TIMEZONE aware and add paper columns
        print("Upgrading 'attendance_records' table...")
        conn.execute(text("""
            ALTER TABLE attendance_records 
            ALTER COLUMN timestamp TYPE TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS paper_name VARCHAR,
            ADD COLUMN IF NOT EXISTS paper_code VARCHAR;
        """))
        
        conn.commit()
        print("Migration completed successfully!")

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"Migration Failed: {e}")
        print("Note: If the columns are already updated, this script might fail. Check your models.py next.")
