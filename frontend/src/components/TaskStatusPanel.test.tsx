import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { LongTask } from '../api';
import TaskStatusPanel from './TaskStatusPanel';

const interruptedTask: LongTask = {
  task_id: 'task-1',
  type: 'generation',
  project_id: 'project_a',
  operation_type: 'generation',
  target_id: 'plan-1',
  user_visible_title: '生成章节',
  status: 'interrupted',
  progress: 42,
  stage: '应用重启，任务已中断',
  message: '应用重启时任务尚未完成，可从任务详情重试',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:01:00Z',
  started_at: '2026-01-01T00:00:10Z',
  finished_at: '2026-01-01T00:01:00Z',
  input_summary: {},
  result: {},
  error: {
    type: 'InterruptedError',
    message: '应用重启时任务尚未完成',
    error_code: 'TASK_INTERRUPTED',
    http_status: null,
    is_timeout: false,
    is_api_key_error: false,
    is_json_parse_error: false,
    retryable: true,
  },
  logs: [],
  current_segment: 1,
  total_segments: 3,
  partial_text: '部分正文',
  partial_word_count: 4,
  draft_id: '',
  can_accept: true,
  timeout_seconds: 3600,
  deadline_at: null,
  attempt: 1,
  retry_of: '',
  retry_available: true,
};

describe('TaskStatusPanel', () => {
  it('shows interrupted state, retained progress and retry action', () => {
    const onRetry = vi.fn();
    render(<TaskStatusPanel task={interruptedTask} onRetry={onRetry} />);

    expect(screen.getAllByText('已中断').length).toBeGreaterThan(0);
    expect(screen.getByText(/分段 1\/3/)).toBeInTheDocument();
    expect(screen.getAllByText(/应用重启时任务尚未完成/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
