import type { ClarifyingQuestion } from "../types";

type Props = {
  questions: ClarifyingQuestion[];
  onChoose: (option: string) => void;
};

export function ClarifyingQuestions({ questions, onChoose }: Props) {
  return (
    <section className="section-block">
      <h3>Clarifying questions</h3>
      <div className="question-list">
        {questions.map((item) => (
          <div className="question-card" key={item.question}>
            <p>{item.question}</p>
            {item.options && item.options.length > 0 && (
              <div className="option-row">
                {item.options.map((option) => (
                  <button key={option} type="button" onClick={() => onChoose(option)}>
                    {option}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
