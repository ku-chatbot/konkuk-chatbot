from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class Enrollment(Base):
    __tablename__ = 'enrollment'
    enrollment_id = Column(Integer, primary_key=True)
    semester = Column(String(20))
    grade = Column(String(5))
    
    student_id = Column(Integer, ForeignKey('student.student_id'))
    course_id = Column(Integer, ForeignKey('course.course_id'))
    
    # Relationship
    student = relationship("Student", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")