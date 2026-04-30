import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, LargeBinary, Float, Enum
from sqlalchemy.orm import declarative_base, relationship
import json

Base = declarative_base()

class Department(Base):
    __tablename__ = 'departments'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    
    users = relationship("User", back_populates="department")
    routines = relationship("Routine", back_populates="department")

class Subject(Base):
    __tablename__ = 'subjects'
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    name = Column(String, index=True)
    
    routines = relationship("Routine", back_populates="subject")

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, index=True) # Unique ID
    name = Column(String)
    enrollment = Column(String, unique=True, index=True)
    role = Column(String, default='student') # student, teacher, hod, admin
    
    # Student specific
    semester = Column(Integer, nullable=True)
    course_name = Column(String, nullable=True)
    major_minor = Column(String, nullable=True)
    
    # Auth
    password_hash = Column(String, nullable=True)
    
    # Relationship to Dept
    department_id = Column(Integer, ForeignKey('departments.id'), nullable=True, index=True)
    department = relationship("Department", back_populates="users")
    
    embedding = Column(LargeBinary) # Store numpy array as bytes
    
    records = relationship("AttendanceRecord", back_populates="user")
    managed_routines = relationship("Routine", back_populates="teacher")

class Routine(Base):
    __tablename__ = 'routines'
    
    id = Column(Integer, primary_key=True, index=True)
    day_of_week = Column(String) # Monday, Tuesday, etc.
    from sqlalchemy import Time
    start_time = Column(Time) # Native TIME
    end_time = Column(Time)   # Native TIME
    
    semester = Column(Integer)
    
    subject_id = Column(Integer, ForeignKey('subjects.id'), index=True)
    teacher_id = Column(Integer, ForeignKey('users.id'), index=True)
    department_id = Column(Integer, ForeignKey('departments.id'), index=True)
    
    subject = relationship("Subject", back_populates="routines")
    teacher = relationship("User", back_populates="managed_routines")
    department = relationship("Department", back_populates="routines")
    attendance_records = relationship("AttendanceRecord", back_populates="routine")

class AttendanceRecord(Base):
    __tablename__ = 'attendance_records'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey('users.user_id'), index=True)
    routine_id = Column(Integer, ForeignKey('routines.id'), nullable=True, index=True)
    
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    device_id = Column(String)
    confidence = Column(Float)
    sync_status = Column(Boolean, default=False)
    
    user = relationship("User", back_populates="records")
    routine = relationship("Routine", back_populates="attendance_records")

class Device(Base):
    __tablename__ = 'devices'

    device_id = Column(String, primary_key=True, index=True)
    is_registered = Column(Boolean, default=False)

class AttendanceHistory(Base):
    __tablename__ = 'attendance_history'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    routine_id = Column(Integer, index=True)
    timestamp = Column(DateTime(timezone=True))
    device_id = Column(String)
    confidence = Column(Float)
    semester = Column(Integer) # Semester when the record was created
    archived_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
