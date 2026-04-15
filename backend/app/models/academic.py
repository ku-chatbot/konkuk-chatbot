from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.models.base import Base


class Student(Base):
    __tablename__ = "student"

    student_id = Column(Integer, primary_key=True, comment="학번")
    name = Column(String(50), nullable=False)
    major = Column(String(50), nullable=False)
    admission_year = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="재학")
    hashed_password = Column(String(160), nullable=False)

    enrollments = relationship("Enrollment", back_populates="student", cascade="all, delete-orphan")
    tuitions = relationship("Tuition", back_populates="student", cascade="all, delete-orphan")


class Professor(Base):
    __tablename__ = "professor"

    professor_id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    email = Column(String(100), nullable=False)
    office = Column(String(50), nullable=False)

    courses = relationship("Course", back_populates="professor")


class Course(Base):
    __tablename__ = "course"

    course_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    credit = Column(Integer, nullable=False)
    room = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    professor_id = Column(Integer, ForeignKey("professor.professor_id"), nullable=False)

    professor = relationship("Professor", back_populates="courses")
    enrollments = relationship("Enrollment", back_populates="course")
    schedules = relationship("Schedule", back_populates="course")
    required_prerequisites = relationship("Prerequisite", foreign_keys="Prerequisite.course_id", back_populates="required_course")
    is_prerequisite_for = relationship("Prerequisite", foreign_keys="Prerequisite.pre_course_id", back_populates="prereq_course")


class Enrollment(Base):
    __tablename__ = "enrollment"

    enrollment_id = Column(Integer, primary_key=True)
    semester = Column(String(20), nullable=False)
    grade = Column(String(5), nullable=True)
    student_id = Column(Integer, ForeignKey("student.student_id"), nullable=False)
    course_id = Column(Integer, ForeignKey("course.course_id"), nullable=False)

    student = relationship("Student", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")


class Schedule(Base):
    __tablename__ = "schedule"

    schedule_id = Column(Integer, primary_key=True)
    day_of_week = Column(String(10), nullable=False)
    start_time = Column(String(10), nullable=False)
    end_time = Column(String(10), nullable=False)
    room = Column(String(50), nullable=False)
    course_id = Column(Integer, ForeignKey("course.course_id"), nullable=False)

    course = relationship("Course", back_populates="schedules")


class Tuition(Base):
    __tablename__ = "tuition"

    tuition_id = Column(Integer, primary_key=True)
    semester = Column(String(20), nullable=False)
    amount = Column(Integer, nullable=False)
    payment_status = Column(Boolean, nullable=False, default=False)
    student_id = Column(Integer, ForeignKey("student.student_id"), nullable=False)

    student = relationship("Student", back_populates="tuitions")


class Prerequisite(Base):
    __tablename__ = "prerequisite"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("course.course_id"), nullable=False)
    pre_course_id = Column(Integer, ForeignKey("course.course_id"), nullable=False)

    __table_args__ = (UniqueConstraint("course_id", "pre_course_id", name="uc_prerequisite_pair"),)

    required_course = relationship("Course", foreign_keys=[course_id], back_populates="required_prerequisites")
    prereq_course = relationship("Course", foreign_keys=[pre_course_id], back_populates="is_prerequisite_for")


class QueryLog(Base):
    __tablename__ = "query_log"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, nullable=True)
    message = Column(Text, nullable=False)
    route = Column(String(20), nullable=False)
    generated_sql = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AcademicDocument(Base):
    __tablename__ = "academic_document"

    id = Column(Integer, primary_key=True)
    title = Column(String(120), nullable=False)
    category = Column(String(40), nullable=False)
    content = Column(Text, nullable=False)
