import re
from random import Random

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AcademicDocument, Base, Course, CoursePrerequisiteNote, Enrollment, Prerequisite, Professor, Schedule, Student, Tuition
from app.db.session import engine


SEMESTER = "2026-1"


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def seed_db(db: Session) -> None:
    if db.query(Student).first():
        return

    rng = Random(42)
    course_specs = _konkuk_2026_1_course_specs()
    professor_names = sorted({spec["professor"] for spec in course_specs})
    professor_contacts = _cse_professor_contacts()
    professors = [
        Professor(
            name=name,
            email=professor_contacts.get(name, ("공식 홈페이지 확인 필요", "공식 홈페이지 확인 필요"))[0],
            office=professor_contacts.get(name, ("공식 홈페이지 확인 필요", "공식 홈페이지 확인 필요"))[1],
        )
        for i, name in enumerate(professor_names, start=1)
    ]
    db.add_all(professors)
    db.flush()
    professor_by_name = {professor.name: professor for professor in professors}

    courses = [
        Course(
            name=spec["name"],
            credit=spec["credit"],
            room=spec["room"],
            description=spec["description"],
            professor_id=professor_by_name[spec["professor"]].professor_id,
        )
        for spec in course_specs
    ]
    db.add_all(courses)
    db.flush()
    course_by_name = {course.name: course for course in courses}

    for spec in course_specs:
        course = course_by_name[spec["name"]]
        for schedule in spec["schedules"]:
            db.add(Schedule(course_id=course.course_id, **schedule))

    prereq_pairs = {
        "알고리즘": "자료구조",
        "데이터베이스": "자료구조",
        "인공지능": "알고리즘",
        "기계학습": "인공지능",
        "자연어처리": "기계학습",
        "졸업프로젝트1(종합설계)": "객체지향개발방법론",
        "졸업프로젝트2(종합설계)": "졸업프로젝트1(종합설계)",
    }
    for course_name, pre_name in prereq_pairs.items():
        target_courses = [course for course in courses if course.name == course_name]
        prereq_course = next((course for course in courses if course.name == pre_name), None)
        if prereq_course:
            db.add_all(Prerequisite(course_id=course.course_id, pre_course_id=prereq_course.course_id) for course in target_courses)
    for note in _official_prerequisite_notes(courses):
        db.add(note)

    majors = ["컴퓨터공학부", "소프트웨어학과", "스마트ICT융합공학과", "인공지능학과"]
    family_names = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
    given_names = ["도윤", "서준", "하준", "지호", "서아", "하은", "지유", "민서", "유찬", "수빈"]
    grade_pool = ["A+", "A0", "B+", "B0", "C+", "P"]
    password = hash_password("password123")
    for offset in range(100):
        student_id = 202214001 + offset
        student = Student(
            student_id=student_id,
            name=f"{family_names[offset % len(family_names)]}{given_names[offset % len(given_names)]}",
            major=majors[offset % len(majors)],
            admission_year=2021 + (offset % 5),
            status="재학" if offset % 11 else "휴학",
            hashed_password=password,
        )
        db.add(student)
        chosen = rng.sample(courses, 5)
        for course in chosen:
            db.add(Enrollment(student_id=student_id, course_id=course.course_id, semester=SEMESTER, grade=rng.choice(grade_pool)))
        db.add(
            Tuition(
                student_id=student_id,
                semester=SEMESTER,
                amount=3_980_000 + (offset % 4) * 120_000,
                payment_status=offset % 3 != 0,
            )
        )

    db.add_all(_academic_documents())
    db.commit()


def _konkuk_2026_1_course_specs() -> list[dict]:
    return [
        _course("데이터베이스", 3, "신효섭", "목04-06(공A1510), 금04-06(공A1510)", "BBAB12001-3173"),
        _course("운영체제", 3, "김욱희", "화07-09(공C487), 목07-09(공C487)", "BBAB12190-3186"),
        _course("자료구조", 3, "김성열", "화01-03(공A602), 목01-03(공A602)", "BBAB12042-3179"),
        _course("알고리즘", 3, "서재형", "화04-06(공B475), 목04-06(공B475)", "BBAB12023-3178"),
        _course("컴퓨터네트워크2", 3, "김기천", "월01-03(공B361), 수01-03(공B361)", "BBAB67036-3236"),
        _course("임베디드시스템소프트웨어", 3, "진현욱", "수05-08(공B475), 금05-08(새502)", "BBAB62246-3226"),
        _course("인공지능", 3, "홍상우", "화10-12(공C487), 목10-12(공C487)", "BBAB62735-3228"),
        _course("웹프로그래밍", 3, "박소영", "월09-12(새502), 수09-12(새502)", "BBAB54724-3195"),
        _course("모바일프로그래밍", 3, "지정희", "월04-06(새402), 수04-06(새402)", "BBAB51979-3190"),
        _course("컴퓨터구조", 3, "박능수", "월04-06(공B352), 수04-06(공B352)", "BBAB59453-3223"),
        _course("졸업프로젝트1(종합설계)", 1, "김욱희", "수17-18(미배정)", "BBAB55840-3200"),
        _course("기계학습", 3, "김학수", "월04-06(공A1510), 수04-06(공A1510)", "BBAB62866-3230"),
        _course("자연어처리", 3, "김학수", "월11-14(공A1510), 수11-14(공A1510)", "BBAB62876-3233"),
    ]


def _official_prerequisite_notes(courses: list[Course]) -> list[CoursePrerequisiteNote]:
    notes = {
        "BBAB12053-3184": (
            "미적분학, 선형대수학, C++ 프로그래밍 역량",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: Prerequisites: Calculus, Linear Algebra, and C++ programming skills.",
        ),
        "BBAB12190-3186": (
            "자료구조, C++ 프로그래밍, 시스템프로그래밍",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: Prerequisite - Data Structure - C++ Programming - System Programming",
        ),
        "BBAB12190-3187": (
            "시스템프로그래밍 수강 권장",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: Students are recommended to complete System Programming class for better understanding of this class.",
        ),
        "BBAB12190-3188": (
            "C프로그래밍, 시스템프로그래밍",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: 선수과목: C프로그래밍, 시스템프로그래밍",
        ),
        "BBAB12190-3189": (
            "C프로그래밍, 시스템프로그래밍",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: 선수과목: C프로그래밍, 시스템프로그래밍",
        ),
        "BBAB62246-3226": (
            "C프로그래밍, 시스템프로그래밍, 운영체제",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: 선수과목: C프로그래밍, 시스템프로그래밍, 운영체제",
        ),
        "BBAB62866-3230": (
            "중급 이상 Python 프로그래밍 능력 필요",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: 본 과목은 일정 수준 이상(클래스 구현, numpy 활용 등 중급 이상)의 Python 프로그래밍 능력을 필요로 합니다.",
        ),
        "BBAB62866-3232": (
            "기초 통계, 선형대수 기초, Python 프로그래밍",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: Prerequisites - Basic knowledge of statistics - Basic knowledge of Linear Algebra - Python Programming",
        ),
        "BBAB67656-3244": (
            "미적분학, 선형대수학, Python 프로그래밍 역량",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: Prerequisites: Calculus, Linear Algebra, and Python programming skills.",
        ),
        "BBAB67656-3245": (
            "미적분학, 선형대수학, Python 프로그래밍 역량",
            "2026학년도 1학기 공식 강의계획서 수강신청 유의사항: Prerequisites: Calculus, Linear Algebra, and Python programming skills.",
        ),
    }
    result = []
    for course in courses:
        matched = next((item for code, item in notes.items() if code in course.description), None)
        if not matched:
            continue
        source_match = re.search(r"BBAB\d+-(\d+)", course.description)
        source_id = source_match.group(1) if source_match else ""
        result.append(
            CoursePrerequisiteNote(
                course_id=course.course_id,
                prerequisites=matched[0],
                note=matched[1],
                source_url=f"https://kupis.konkuk.ac.kr/sugang/acd/cour/plan/CourLecturePlanInq.jsp?ltShtm=B01011&ltYy=2026&sbjtId={source_id}",
            )
        )
    return result


def _cse_professor_contacts() -> dict[str, tuple[str, str]]:
    # 건국대학교 컴퓨터공학부 공식 교수진 페이지 기준: https://www.konkuk.ac.kr/cse/9960/subview.do
    return {
        "김기천": ("kckim@konkuk.ac.kr", "공C385-2"),
        "김성열": ("kimsr@konkuk.ac.kr", "공C483-2"),
        "김욱희": ("wookhee@konkuk.ac.kr", "공C422"),
        "김학수": ("nlpdrkim@konkuk.ac.kr", "공C386-1"),
        "김형석": ("hyuskim@konkuk.ac.kr", "신공학관 1006호"),
        "문창주": ("cjmoon@konkuk.ac.kr", "공C285"),
        "민덕기": ("dkmin@konkuk.ac.kr", "공C385"),
        "박능수": ("neungsoo@konkuk.ac.kr", "공C384-1"),
        "박소영": ("soyoungpark@konkuk.ac.kr", "공C421"),
        "서재형": ("seojae777@konkuk.ac.kr", "공A1409-1"),
        "신효섭": ("hsshin@konkuk.ac.kr", "공C386-2"),
        "오병국": ("bkoh@konkuk.ac.kr", "공C384-2"),
        "유준범": ("jbyoo@konkuk.ac.kr", "공C386"),
        "윤경로": ("yoonk@konkuk.ac.kr", "공C384"),
        "이향원": ("leehw@konkuk.ac.kr", "공C293-1"),
        "임민규": ("mlim@konkuk.ac.kr", "공C292-1"),
        "임창훈": ("cyim@konkuk.ac.kr", "공C292-3"),
        "정갑주": ("jeongk@konkuk.ac.kr", "공C385-1"),
        "지서원": ("seowonji@konkuk.ac.kr", "공C484"),
        "지정희": ("jhchi@konkuk.ac.kr", "공C421"),
        "진현욱": ("jinh@konkuk.ac.kr", "공C291-1"),
        "차영운": ("youngcha@konkuk.ac.kr", "공C293-2"),
        "하영국": ("ygha@konkuk.ac.kr", "공C291-2"),
        "홍상우": ("swhong06@konkuk.ac.kr", "공A1513"),
    }


def _course(name: str, credit: int, professor: str, room_text: str, official_id: str) -> dict:
    return {
        "name": name,
        "credit": credit,
        "professor": professor,
        "room": room_text,
        "description": f"2026학년도 1학기 건국대학교 종합강의시간표 기준 실제 개설 과목입니다. 공식 식별자: {official_id}.",
        "schedules": _parse_room_text(room_text),
    }


def _parse_room_text(room_text: str) -> list[dict[str, str]]:
    schedules = []
    for item in room_text.split(","):
        item = item.strip()
        if "(" not in item or ")" not in item:
            continue
        day = item[0]
        period = item[1 : item.index("(")]
        room = item[item.index("(") + 1 : item.rindex(")")]
        start, end = period.split("-", 1) if "-" in period else (period, period)
        schedules.append({"day_of_week": day, "start_time": f"{start}교시", "end_time": f"{end}교시", "room": room})
    return schedules or [{"day_of_week": "미정", "start_time": "미정", "end_time": "미정", "room": room_text}]


def _academic_documents() -> list[AcademicDocument]:
    return [
        AcademicDocument(
            title="휴학 신청 안내",
            category="학적",
            content="일반휴학 신청은 학기 개시 전 지정 기간에 포털 학사서비스에서 신청합니다. 군휴학은 입영통지서 등 증빙서류를 제출해야 하며, 승인 후 학적 상태가 휴학으로 변경됩니다.",
        ),
        AcademicDocument(
            title="복학 신청 안내",
            category="학적",
            content="복학 예정자는 정해진 복학 신청 기간에 포털에서 신청해야 합니다. 등록금 납부와 수강신청은 복학 승인 이후 진행할 수 있습니다.",
        ),
        AcademicDocument(
            title="수강신청 정정",
            category="수업",
            content="수강신청 정정 기간에는 여석이 있는 과목에 한해 수강 과목을 추가하거나 삭제할 수 있습니다. 정정 완료 후 개인 시간표를 반드시 확인해야 합니다.",
        ),
        AcademicDocument(
            title="졸업 요건",
            category="졸업",
            content="졸업을 위해서는 전공 필수, 전공 선택, 교양, 총 이수 학점, 졸업 프로젝트 또는 졸업 논문 요건을 충족해야 합니다. 세부 기준은 입학년도와 학과별 교육과정에 따라 다릅니다.",
        ),
        AcademicDocument(
            title="장학 제도",
            category="장학",
            content="성적장학, 국가장학, 근로장학, 교내외 특별장학이 운영됩니다. 장학금은 신청 자격, 성적 기준, 소득 구간, 제출 서류에 따라 심사됩니다.",
        ),
        AcademicDocument(
            title="등록금 납부",
            category="등록",
            content="등록금은 지정된 납부 기간에 가상계좌 또는 카드 납부 방식으로 납부합니다. 납부 완료 여부는 포털 등록금 조회 메뉴에서 확인할 수 있습니다.",
        ),
        AcademicDocument(
            title="출석 인정",
            category="수업",
            content="질병, 경조사, 예비군 훈련 등 정당한 사유가 있는 경우 증빙서류를 제출하여 출석 인정을 신청할 수 있습니다. 인정 범위는 학사 운영 규정에 따릅니다.",
        ),
        AcademicDocument(
            title="전과 및 다전공",
            category="학적",
            content="전과, 복수전공, 부전공 신청은 정해진 기간에 접수하며 학점, 성적, 학과별 심사 기준을 충족해야 합니다.",
        ),
    ]
