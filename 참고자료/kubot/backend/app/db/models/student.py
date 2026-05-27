from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship
from .base import Base

class Student(Base):
    __tablename__ = 'student'
    student_id = Column(Integer, primary_key=True, comment="학번")
    name = Column(String(50), nullable=False)
    major = Column(String(50))
    admission_year = Column(Integer)
    status = Column(String(20)) # 재학/휴학/졸업
    # 비밀번호 컬럼 추가 (로그인을 위해 필요)
    hashed_password = Column(String(100), nullable=False) 
    
    # Relationship
    enrollments = relationship("Enrollment", back_populates="student")
    tuitions = relationship("Tuition", back_populates="student")