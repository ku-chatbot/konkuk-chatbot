from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from .base import Base

class Professor(Base):
    __tablename__ = 'professor'
    professor_id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    email = Column(String(100))
    office = Column(String(50))
    
    # Relationship
    courses = relationship("Course", back_populates="professor")