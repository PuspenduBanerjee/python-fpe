import difflib

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine, DeanonymizeEngine
from presidio_anonymizer.entities.engine import RecognizerResult, OperatorConfig
from random import shuffle
from faker import Faker


def anonymize(text, results, deanonymize=False):
    # Initialize the engine with logger.
    engine = DeanonymizeEngine() if deanonymize else AnonymizerEngine()
    key = "EF4359D8D580AA4F7F036D6F04FC6A94"
    tweak = "D8E7920AFA330A73"

    operators = {
        "PERSON": OperatorConfig("encrypt", {"key": key, "encryption": "FPEFF31", "tweak": tweak, "radix": 64}),
        "PHONE_NUMBER": OperatorConfig("mask", {"type": "mask", "masking_char": "*", "chars_to_mask": 6,
                                                "from_end": False}),
        "US_SSN": OperatorConfig("encrypt", {"key": key, "encryption": "FPEFF31", "tweak": tweak, "radix": 10})
    }

    if deanonymize:
        result = engine.deanonymize(
            text=text,
            entities=results,
            operators=operators
        )
    else:
        # Invoke the anonymize function with the text, analyzer results and
        # Operators to define the anonymization type.
        result = engine.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators
        )

    return result


def analyze(text, analyzer: AnalyzerEngine):
    results = analyzer.analyze(text=text, entities=["PERSON", "PHONE_NUMBER", "US_SSN"], language='en')
    return results


def scramble(input_text, times=10):
    parts = input_text.split(' ')
    shuffle(parts)
    return " ".join(parts)


if __name__ == '__main__':
    fake = Faker()
    for run in range(3):
        last_name = fake.last_name()
        first_name = fake.first_name()
        phone_num = fake.phone_number()
        ssn = fake.ssn()
        text = f"My name is {last_name}, {first_name} {last_name}! nah it's actually Puspendu Banerjee " \
               f"and my phone number is {phone_num}. Note my SSN: {ssn}"
        print(f"Input:  {text}")
        analyzer = AnalyzerEngine(supported_languages=["en","es"],log_decision_process=False)
        analyzer_result = analyze(text, analyzer)
        # Additionally, say that we know the the 1st Bond words in the sentence is a Surname and want to apply same FPE
        # there. To achieve that we can manipulate the result from analyzer as follows:
        # analyzer_result.append(RecognizerResult("PERSON", 11, 15, 0.8))
        result = anonymize(text, analyzer_result)
        result_text_list = result.text.split(' ')
        diffed_output_list = sorted(list(filter(lambda pq: pq[0] != pq[1],
                                         [(p, result_text_list[idx]) for idx, p in enumerate(text.split(' '))])))
        print(f"Anonymized: {result.text}")
        # De-anonymize
        # result = anonymize(text,list(result),deanonymize=True)
        # print(f"De-anonymized: {result.text}")

        print(diffed_output_list)
        print("="*5)

