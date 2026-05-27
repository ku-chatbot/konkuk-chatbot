from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from .base import Base

class Tuition(Base):
    __tablename__ = 'tuition'
    tuition_id = Column(Integer, primary_key=True)
    semester = Column(String(20))
    amount = Column(Integer)
    payment_status = Column(Boolean)
    
    student_id = Column(Integer, ForeignKey('student.student_id'))
    
    # Relationship
    student = relationship("Student", back_populates="tuitions")