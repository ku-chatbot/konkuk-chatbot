# 모든 모델 파일을 import하여 Base.metadata에 등록합니다.
from .base import Base 
from .student import Student
from .professor import Professor
from .course import Course
from .enrollment import Enrollment
from .tuition import Tuition
from .schedule import Schedule
from .prerequisite import Prerequisite