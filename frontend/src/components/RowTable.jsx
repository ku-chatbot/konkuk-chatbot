import React from 'react'

const COLUMN_LABELS = {
  semester: '학기',
  course_name: '과목',
  credit: '학점',
  grade: '성적',
  room: '강의실',
  professor_name: '담당 교수',
  email: '이메일',
  office: '연구실',
  day_of_week: '요일',
  start_time: '시작',
  end_time: '종료',
  amount: '금액',
  payment_status: '납부',
  prerequisite_name: '선수과목',
  student_id: '학번',
  name: '이름',
  major: '학과',
  admission_year: '입학년도',
  status: '상태',
}

function formatCell(key, value) {
  if (value === null || value === undefined) return '-'
  if (key === 'amount' && typeof value === 'number') {
    return `${value.toLocaleString('ko-KR')}원`
  }
  if (key === 'payment_status') {
    return value ? '완납' : '미납'
  }
  return String(value)
}

export default function RowTable({ rows }) {
  if (!rows || rows.length === 0) return null
  const columns = Object.keys(rows[0])
  return (
    <div className="row-table-wrap">
      <table className="row-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col}>{COLUMN_LABELS[col] || col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map((col) => (
                <td key={col}>{formatCell(col, row[col])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
