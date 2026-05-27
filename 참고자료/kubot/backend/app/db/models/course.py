from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from .base import Base

class Course(Base):
    __tablename__ = 'course'
    course_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    credit = Column(Integer)
    room = Column(String(50))
    description = Column(Text)
    
    professor_id = Column(Integer, ForeignKey('professor.professor_id'))
    
    # Relationship 
    professor = relationship("Professor", back_populates="courses")
    enrollments = relationship("Enrollment", back_populates="course")
    # 1. Schedule과의 관계 (1:N)
    schedules = relationship("Schedule", back_populates="course")
    # 2. 선수 과목 관계 (N:M, Prerequisite 테이블을 통한 자기 참조)
    # 해당 과목이 요구하는 선수 과목 목록
    required_prerequisites = relationship("Prerequisite", foreign_keys="Prerequisite.course_id", back_populates="required_course")
    # 이 과목을 선수 과목으로 요구하는 다른 과목 목록
    is_prerequisite_for = relationship("Prerequisite", foreign_keys="Prerequisite.pre_course_id", back_populates="prereq_course")