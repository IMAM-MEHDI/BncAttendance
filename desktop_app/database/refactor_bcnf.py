import sys
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Add the desktop_app directory to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SQLALCHEMY_DATABASE_URL
from database import models

def refactor_to_bcnf():
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    
    print("Connecting to database for BCNF refactor...")
    
    # 1. Create the new subjects table if it doesn't exist
    models.Base.metadata.create_all(bind=engine)
    
    with engine.connect() as conn:
        # Check if we've already refactored
        result = conn.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name='routines' AND column_name='paper_code'"))
        if result.scalar() == 0:
            print("Database already refactored or columns missing. Skipping migration.")
            return

        print("Migrating papers from routines to subjects...")
        # Get unique papers from routines
        papers = conn.execute(text("SELECT DISTINCT paper_code, paper_name FROM routines WHERE paper_code IS NOT NULL")).fetchall()
        
        for code, name in papers:
            conn.execute(text("INSERT INTO subjects (code, name) VALUES (:code, :name) ON CONFLICT (code) DO NOTHING"), 
                         {"code": code, "name": name})
        
        # 2. Add subject_id column to routines if not exists
        print("Adding subject_id to routines...")
        conn.execute(text("ALTER TABLE routines ADD COLUMN IF NOT EXISTS subject_id INTEGER REFERENCES subjects(id)"))
        
        # 3. Update routines with subject_id
        print("Linking routines to subjects...")
        conn.execute(text("""
            UPDATE routines 
            SET subject_id = subjects.id 
            FROM subjects 
            WHERE routines.paper_code = subjects.code
        """))
        
        # 4. Remove redundant columns from routines
        print("Removing redundant columns from routines...")
        conn.execute(text("ALTER TABLE routines DROP COLUMN paper_name"))
        conn.execute(text("ALTER TABLE routines DROP COLUMN paper_code"))
        
        # 5. Remove redundant columns from attendance_records
        print("Removing redundant columns from attendance_records...")
        conn.execute(text("ALTER TABLE attendance_records DROP COLUMN paper_name"))
        conn.execute(text("ALTER TABLE attendance_records DROP COLUMN paper_code"))
        
        conn.commit()
        print("Refactor to BCNF completed successfully!")

if __name__ == "__main__":
    try:
        refactor_to_bcnf()
    except Exception as e:
        print(f"Refactor Failed: {e}")
