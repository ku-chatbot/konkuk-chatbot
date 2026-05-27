from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .base import Base

class Prerequisite(Base):
    __tablename__ = 'prerequisite'
    
    # 복합 키 대신 PK를 사용하고 UniqueConstraint로 중복 방지
    id = Column(Integer, primary_key=True) 
    
    # Foreign Keys:
    course_id = Column(Integer, ForeignKey('course.course_id'), comment="선수 과목을 요구하는 본 과목")
    pre_course_id = Column(Integer, ForeignKey('course.course_id'), comment="선수 과목")
    
    # 한 과목이 특정 선수 과목을 두 번 요구할 수 없으므로 Unique Constraint 추가
    __table_args__ = (
        UniqueConstraint('course_id', 'pre_course_id', name='uc_prerequisite_pair'),
    )
    
    # Relationship: Course 모델의 relationship에서 back_populates를 위해 필요
    required_course = relationship("Course", foreign_keys=[course_id], back_populates="required_prerequisites")
    prereq_course = relationship("Course", foreign_keys=[pre_course_id], back_populates="is_prerequisite_for")