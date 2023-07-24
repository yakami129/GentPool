import multiprocessing
import random
import time
from typing import Tuple

from gentopia.agent import BaseAgent
from gentopia.model import AgentOutput

from gentpool.bench.grader import BaseGrader
from gentpool.bench.eval import BaseEval
from gentpool.bench.eval.base_eval import EvalResult
from gentpool.bench.prompt.code_eval import APPSPrompt, HumanEvalPrompt, MBPPPrompt
from .utils import *
import os


class CodeEval(BaseEval):
    """
    Evaluation class for coding tasks. 
    Such tasks should have the following keys in the json file:
    - problem: the problem description
    - test_case: the test cases to the problem
    - dataset: the dataset the task belongs to
    Now the dataset is temporarily hard-coded to support 3 types of datasets ["apps", "humaneval" and "mbpp"].
    """
    eval_class: str
    eval_subclass: str
    grader: Optional[BaseGrader] = None

    def _print_result(self, result: EvalResult):
        output = [
            "\n### FINISHING Agent EVAL ###",
            f"Agent score: {result.score * 100}",
            f"Agent run exception rate: {result.fail_rate * 100}%",
            f"Avg runtime per task: {round(result.avg_runtime, 2)}s",
            f"Avg cost per 1000 runs: ${round(result.avg_cost * 1000, 3)}",
            f"Avg token usage per task: {round(result.avg_token_usage, 1)} tokens",
            f"... And the total cost for evaluation ${round(result.eval_cost, 5)}"
        ]

        for line in output:
            print(line, end=' ', flush=True)
            time.sleep(0.7)
            print()

        if result.score >= 0.8:
            print("Excellent Scoring! (ﾉ◕ヮ◕)ﾉ*:･ﾟ✧")
        elif result.score >= 0.6:
            print("It passed, at least. (￣▽￣)ノ")
        else:
            print(f"Your agent needs some tuning for {self.eval_class}/{self.eval_subclass}. (╯°□°）╯︵ ┻━┻)")

    def evaluate(self, agent: BaseAgent, n_smaple: int, seed=0, private=False, verbose=True,
                 time_limit=5, grade=False) -> EvalResult:
        ## Randomly sample
        if self.data is None:
            self.data = self._get_data(seed, private, n_smaple)

        total_score, total_cost, total_token, total_runtime, num_failed, eval_grader_cost, count = [0] * 7
        for task in self.data:
            count += 1
            st = time.time()
            problem = task.get("problem", None)
            dataset = task.get("dataset", None)
            if dataset == "apps":
                agent_instruction = APPSPrompt.format(problem=problem)
            elif dataset == "humaneval":
                agent_instruction = HumanEvalPrompt.format(problem=problem)
            elif dataset == "mbpp":
                agent_instruction = MBPPPrompt.format(problem=problem)

            try:
                response = agent.run(agent_instruction)
                assert response is not None
                if verbose:
                    print("> Agent run successful.")
            except Exception as e:
                num_failed += 1
                response = AgentOutput(output="Agent failed", cost=0, token_usage=0)
                if verbose:
                    print("> Agent run failed.")
            et = time.time() - st
            total_cost += response.cost
            total_token += response.token_usage

            if response.output != "Agent failed":
                total_runtime += et
                if dataset == "apps":
                    test = convert_apps_code(response.output, task["test_case"])
                elif dataset == "humaneval":
                    test = response.output + "\n" + task["test_case"]
                elif dataset == "mbpp":
                    test = response.output + "\n" + task["test_case"]
                output = check_correctness(test, time_limit)
                if verbose:
                    print(f"> Grader: {output}")
                eval_grader_cost += 0
                if "pass" in output.lower():
                    total_score += 1

        valid_sample = n_smaple - num_failed

        result = EvalResult(score=0 if not n_smaple else total_score / n_smaple,
                            fail_rate=0 if not n_smaple else num_failed / n_smaple,
                            avg_runtime=0 if not valid_sample else total_runtime / valid_sample,
                            avg_cost=0 if not valid_sample else total_cost / valid_sample,
                            avg_token_usage=0 if not valid_sample else total_token / valid_sample,
                            eval_cost=eval_grader_cost)

        if verbose:
            self._print_result(result)
        return result

    def eval_async(self, agent: BaseAgent, n_smaple: int, seed: int = 0, *args, **kwargs) -> EvalResult:
        raise NotImplementedError("Async evaluation not supported yet.")

    def evaluate_single(self, agent: BaseAgent, index: int, n_smaple: int, seed=0, private=False, verbose=True,
                 time_limit=5) -> Tuple["CodeEval", int, EvalResult, AgentOutput]:
        if self.data is None:
            self.data = self._get_data(seed, private, n_smaple)

        total_score, total_cost, total_token, total_runtime, num_failed, eval_grader_cost = [0] * 6
        task = self.data[index]

        st = time.time()
        problem = task.get("problem", None)
        dataset = task.get("dataset", None)
        if dataset == "apps":
            agent_instruction = APPSPrompt.format(problem=problem)
        elif dataset == "humaneval":
            agent_instruction = HumanEvalPrompt.format(problem=problem)
        elif dataset == "mbpp":
            agent_instruction = MBPPPrompt.format(problem=problem)

        try:
            response = agent.run(agent_instruction)
            assert response is not None
            if verbose:
                print("> Agent run successful.")
        except Exception as e:
            num_failed += 1
            response = AgentOutput(output="Agent failed", cost=0, token_usage=0)
            if verbose:
                print("> Agent run failed.")
        et = time.time() - st
        total_cost += response.cost
        total_token += response.token_usage

        if response.output != "Agent failed":
            total_runtime += et
            if dataset == "apps":
                test = convert_apps_code(response.output, task["test_case"])
            elif dataset == "humaneval":
                test = response.output + "\n" + task["test_case"]
            elif dataset == "mbpp":
                test = response.output + "\n" + task["test_case"]
            output = check_correctness(test, time_limit)
            if verbose:
                print(f"> Grader: {output}")
            eval_grader_cost += 0
            if "pass" in output.lower():
                total_score += 1

        valid_sample = n_smaple - num_failed

        result = EvalResult(score=0,
                            fail_rate=num_failed,
                            avg_runtime=total_runtime,
                            avg_cost=total_cost,
                            avg_token_usage=total_token,
                            eval_cost=0)

        if verbose:
            self._print_result(result)
        return self, index, result, response

    def grade_single(self, response: AgentOutput, index:int, verbose: bool=False) -> Tuple["CodeEval", EvalResult]:
        task = self.data[index]
        eval_grader_cost, total_score = 0, 0
        dataset = task.get("dataset", None)
        if response.output != "Agent failed":
            if dataset == "apps":
                test = convert_apps_code(response.output, task["test_case"])
            elif dataset == "humaneval":
                test = response.output + "\n" + task["test_case"]
            elif dataset == "mbpp":
                test = response.output + "\n" + task["test_case"]
            output = check_correctness(test, time_limit)
            if verbose:
                print(f"> Grader: {output}")
            eval_grader_cost += 0
            if "pass" in output.lower():
                total_score += 1
        return self, EvalResult(score=total_score,
                   fail_rate=0 ,
                   avg_runtime=0,
                   avg_cost=0 ,
                   avg_token_usage=0,
                   eval_cost=eval_grader_cost)
