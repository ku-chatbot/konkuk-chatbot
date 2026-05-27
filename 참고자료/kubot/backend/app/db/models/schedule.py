from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class Schedule(Base):
    __tablename__ = 'schedule'
    schedule_id = Column(Integer, primary_key=True)
    day_of_week = Column(String(10), comment="강의 요일 (예: 월, 화)")
    start_time = Column(String(10), comment="강의 시작 시간 (예: 10:30)")
    end_time = Column(String(10), comment="강의 종료 시간")
    room = Column(String(50), comment="강의실 위치")
    
    # Foreign Key: 어떤 강좌의 시간표인지 연결
    course_id = Column(Integer, ForeignKey('course.course_id'))
    
    # Relationship: Course 모델로의 역참조를 위한 설정
    course = relationship("Course", back_populates="schedules")