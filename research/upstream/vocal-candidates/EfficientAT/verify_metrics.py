"""Run hand-computable sklearn API fixtures; not a model-output parity test."""
import json

import numpy as np
import sklearn
from sklearn import metrics, preprocessing


def main():
    if sklearn.__version__ != '1.5.2':
        raise RuntimeError(f'Expected migrated scikit-learn 1.5.2, got {sklearn.__version__}')
    targets = np.array([[0, 1], [0, 1], [1, 0], [1, 0]])
    outputs = np.array([[.1, .9], [.4, .6], [.35, .65], [.8, .2]])
    np.testing.assert_allclose(metrics.average_precision_score(targets, outputs, average=None), [5 / 6, 5 / 6])
    np.testing.assert_allclose(metrics.roc_auc_score(targets, outputs, average=None), [.75, .75])
    if metrics.accuracy_score([0, 1, 1, 0], [0, 1, 0, 0]) != .75:
        raise AssertionError('Accuracy fixture mismatch')
    if preprocessing.LabelEncoder().fit_transform(['b', 'a', 'b']).tolist() != [1, 0, 1]:
        raise AssertionError('LabelEncoder fixture mismatch')
    print(json.dumps({'status': 'passed', 'scikitLearn': sklearn.__version__,
                      'numpy': np.__version__, 'scope': 'four hand-computable API fixtures',
                      'modelParityEstablished': False}))


if __name__ == '__main__':
    main()
