import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastProvider, useToast } from './Toast';

function Harness() {
  const { notify } = useToast();
  return (
    <>
      <button onClick={() => notify('Saved.', 'success')}>succeed</button>
      <button onClick={() => notify('It broke.', 'error')}>fail</button>
    </>
  );
}

describe('ToastProvider', () => {
  it('shows a notification when one is raised', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );

    await user.click(screen.getByText('succeed'));

    expect(screen.getByText('Saved.')).toBeInTheDocument();
  });

  it('announces politely so a screen reader is not interrupted', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );
    await user.click(screen.getByText('succeed'));

    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
  });

  it('dismisses on demand', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );
    await user.click(screen.getByText('fail'));

    await user.click(screen.getByRole('button', { name: /Dismiss/ }));

    expect(screen.queryByText('It broke.')).not.toBeInTheDocument();
  });

  it('stacks multiple notifications', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );

    await user.click(screen.getByText('succeed'));
    await user.click(screen.getByText('fail'));

    expect(screen.getByText('Saved.')).toBeInTheDocument();
    expect(screen.getByText('It broke.')).toBeInTheDocument();
  });

  it('does not throw when used outside a provider', () => {
    // The no-op fallback is what lets a component be rendered in isolation
    // (a test, a preview harness) without dragging the provider along.
    expect(() => render(<Harness />)).not.toThrow();
  });
});
