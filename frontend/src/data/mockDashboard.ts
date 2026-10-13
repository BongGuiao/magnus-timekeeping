import type { EmployeeDashboardData } from '../types/dashboard'

// TODO: replace with a real API call (e.g. GET /employees/me/dashboard) once the backend endpoint exists.
export const mockDashboardData: EmployeeDashboardData = {
  employeeName: 'Juan Dela Cruz',
  employeeCode: 'N10234',
  today: {
    clockInAt: '08:02 AM',
    clockOutAt: null,
    isOnBreak: false,
  },
  workHours: {
    weeklyHours: 32.5,
    weeklyTarget: 48,
    monthlyHours: 128,
    monthlyTarget: 176,
  },
  leaveBalances: [
    { type: 'sick', label: 'Sick Leave', allotted: 10, used: 3 },
    { type: 'vacation', label: 'Vacation Leave', allotted: 15, used: 6 },
    { type: 'maternity', label: 'Maternity Leave', allotted: 105, used: 0 },
    { type: 'paternity', label: 'Paternity Leave', allotted: 7, used: 0 },
    { type: 'birthday', label: 'Birthday Leave', allotted: 1, used: 0 },
    { type: 'other', label: 'Other Leave', allotted: 3, used: 1 },
  ],
  attendanceExceptions: {
    noLogin: 2,
    noLogout: 1,
    periodLabel: 'This month',
  },
  recentAttendance: [
    { date: '2026-09-26', timeIn: '08:01 AM', timeOut: '05:03 PM', status: 'present' },
    { date: '2026-09-25', timeIn: '08:15 AM', timeOut: '05:00 PM', status: 'late' },
    { date: '2026-09-24', timeIn: '07:58 AM', timeOut: null, status: 'no-logout' },
    { date: '2026-09-23', timeIn: null, timeOut: '05:01 PM', status: 'no-login' },
    { date: '2026-09-22', timeIn: null, timeOut: null, status: 'on-leave' },
  ],
  leaveRequests: [
    { id: 'lr-1', type: 'vacation', startDate: '2026-10-05', endDate: '2026-10-07', status: 'pending' },
    { id: 'lr-2', type: 'sick', startDate: '2026-09-22', endDate: '2026-09-22', status: 'approved' },
  ],
  upcomingHolidays: [
    { date: '2026-10-31', name: 'All Saints\' Day (Special Non-Working)' },
    { date: '2026-11-30', name: 'Bonifacio Day' },
  ],
  announcements: [
    { id: 'a-1', title: 'Company outing scheduled for November 14', postedAt: '2026-09-20' },
    { id: 'a-2', title: 'New biometric terminal installed at Main Gate', postedAt: '2026-09-18' },
  ],
}
