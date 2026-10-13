export interface Step {
  label: string
  description?: string
}

interface Props {
  steps: Step[]
  /** Zero-based index of the step currently in progress. */
  currentStep: number
}

export default function Stepper({ steps, currentStep }: Props) {
  return (
    <ol className="flex items-start">
      {steps.map((step, index) => {
        const isComplete = index < currentStep
        const isCurrent = index === currentStep
        const isLast = index === steps.length - 1

        return (
          <li key={step.label} className={`flex items-start ${isLast ? '' : 'flex-1'}`}>
            <div className="flex flex-col items-center">
              <span
                className={`flex h-9 w-9 items-center justify-center rounded-full border-2 text-xs font-bold transition ${
                  isComplete
                    ? 'border-emerald-500 bg-emerald-500 text-white'
                    : isCurrent
                      ? 'border-indigo-600 bg-indigo-600 text-white ring-4 ring-indigo-100'
                      : 'border-slate-200 bg-white text-slate-400'
                }`}
              >
                {isComplete ? '✓' : index + 1}
              </span>
              <div className="mt-2 w-28 text-center sm:w-36">
                <p
                  className={`text-xs font-bold uppercase tracking-wide ${
                    isComplete ? 'text-emerald-600' : isCurrent ? 'text-indigo-600' : 'text-slate-400'
                  }`}
                >
                  {step.label}
                </p>
                {step.description && (
                  <p className="mt-0.5 hidden text-[11px] leading-snug text-slate-400 sm:block">{step.description}</p>
                )}
              </div>
            </div>

            {!isLast && (
              <div
                className={`mt-[18px] h-0.5 flex-1 rounded-full transition ${
                  isComplete ? 'bg-emerald-500' : 'bg-slate-200'
                }`}
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}
