from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Ensure `app` is importable when running pytest from repo root or backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Force OpenAI key off so openai_service.* return None by default.
os.environ["OPENAI_API_KEY"] = ""
os.environ["UPSTAGE_API_KEY"] = ""

from app.core.security import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Course,
    Enrollment,
    Prerequisite,
    Professor,
    Schedule,
    Student,
    Tuition,
)


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine) -> Session:
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    session = SessionLocal()
    try:
        _seed_minimal(session)
        yield session
    finally:
        session.close()


@pytest.fixture
def other_db(engine) -> Session:
    """A second session sharing the same engine, used to verify cross-student isolation."""
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def student(db) -> Student:
    return db.query(Student).filter(Student.student_id == 202214001).one()


@pytest.fixture
def other_student(db) -> Student:
    return db.query(Student).filter(Student.student_id == 202214002).one()


def _seed_minimal(db: Session) -> None:
    password = hash_password("password123")

    professor = Professor(name="홍길동", email="hong@konkuk.ac.kr", office="공A101")
    other_prof = Professor(name="김철수", email="kim@konkuk.ac.kr", office="공A102")
    db.add_all([professor, other_prof])
    db.flush()

    courses = [
        Course(name="데이터베이스", credit=3, room="공A1510", description="DB 강의", professor_id=professor.professor_id),
        Course(name="자료구조", credit=3, room="공A602", description="DS 강의", professor_id=professor.professor_id),
        Course(name="알고리즘", credit=3, room="공B475", description="ALGO 강의", professor_id=other_prof.professor_id),
        Course(name="운영체제", credit=3, room="공C487", description="OS 강의", professor_id=other_prof.professor_id),
    ]
    db.add_all(courses)
    db.flush()

    db.add(Schedule(course_id=courses[0].course_id, day_of_week="목", start_time="04교시", end_time="06교시", room="공A1510"))
    db.add(Schedule(course_id=courses[1].course_id, day_of_week="화", start_time="01교시", end_time="03교시", room="공A602"))

    db.add(Prerequisite(course_id=courses[2].course_id, pre_course_id=courses[1].course_id))
    db.add(Prerequisite(course_id=courses[0].course_id, pre_course_id=courses[1].course_id))

    students = [
        Student(student_id=202214001, name="김도윤", major="컴퓨터공학부", admission_year=2022, status="재학", hashed_password=password),
        Student(student_id=202214002, name="이서준", major="소프트웨어학과", admission_year=2022, status="재학", hashed_password=password),
    ]
    db.add_all(students)
    db.flush()

    db.add(Enrollment(student_id=202214001, course_id=courses[0].course_id, semester="2026-1", grade="A+"))
    db.add(Enrollment(student_id=202214001, course_id=courses[1].course_id, semester="2026-1", grade="B+"))
    db.add(Enrollment(student_id=202214001, course_id=courses[2].course_id, semester="2026-1", grade=None))
    db.add(Enrollment(student_id=202214002, course_id=courses[3].course_id, semester="2026-1", grade="A0"))

    db.add(Tuition(student_id=202214001, semester="2026-1", amount=4_100_000, payment_status=True))
    db.add(Tuition(student_id=202214002, semester="2026-1", amount=3_980_000, payment_status=False))

    db.commit()
