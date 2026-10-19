# Machine learning workflow
<!-- tools: -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md, Doc/ml/ -->

Goal: {description}

Read the local `Doc/ml/` knowledge corpus before designing an example-based ML workflow. There is no local training orchestrator; dataset writes, TOP cooks, training, and external execution remain separately governed.

## Decisions

- Use ML only when inputs and targets can be represented as a stable fixed-dimensional mapping and approximation error is acceptable.
- Split dataset generation, input and target representation, preprocessing, train/validation partitioning, training, evaluation, serialization, and inference.
- Keep preprocessing and serialization identical between training and inference.

## Order of work

1. Define the supervisor mapping, input representation, target representation, expected error, and acceptance metric.
2. Generate a small deterministic dataset and inspect individual labeled examples.
3. Partition training and validation data without leakage from related samples.
4. Establish a simple baseline before neural-network training.
5. Authorize dataset writes and TOP training separately; record seeds, versions, logs, and model artifacts.
6. Evaluate unseen examples and compare inference against the original procedural result before integration.

## Failure signatures

- Low training loss with poor validation indicates overfitting, leakage, or an unrepresentative dataset.
- Inference mismatch often comes from inconsistent serialization, preprocessing, units, or topology.
- A model that appears fast but violates the accepted error metric is not a valid replacement for the supervisor.