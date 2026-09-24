"""Class refiner experiment, step 2 (design.md §18): train + evaluate on features.csv.

    python -m scripts.train_class_refiner [--model logreg|lightgbm]

5-fold GroupKFold by image id (a screenshot is never split across train/test), then
a final model on all data. Writes output/class_refiner/testN_<model>/:
metrics.json, classification_report.txt, feature_weights.csv, model.joblib, run_config.json,
and the charts (confusion_matrix, confusion_confusable, per_class_metrics, reliability,
feature_weights .png) gathered on one page in report.html.
"""
import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts import _refiner_plots as plots
from scripts._test_utils import next_test_number
from scripts.build_refiner_dataset import CONFIG_PATH, META_COLUMNS, load_config


def load_training_data(cfg, exclude_images=()):
    """(df, feature columns, excluded class counts). Drops the excluded classes and images."""
    df = pd.read_csv(Path(cfg["paths"]["output_dir"]) / "features.csv", keep_default_na=False)
    excluded = {c: int((df.label == c).sum()) for c in cfg["exclude_from_training"]}
    df = df[~df.label.isin(cfg["exclude_from_training"]) & ~df.image_id.isin(exclude_images)].reset_index(drop=True)
    return df, [c for c in df.columns if c not in META_COLUMNS], excluded


def make_model(kind, cfg):
    m = cfg["model"]
    if kind == "logreg":
        # lbfgs on >2 classes is multinomial (sklearn's default since 1.5)
        return make_pipeline(StandardScaler(), LogisticRegression(
            class_weight="balanced", random_state=m["seed"], **m["logreg"]))
    from lightgbm import LGBMClassifier
    from sklearn.calibration import CalibratedClassifierCV
    # LightGBM probabilities are not calibrated (design.md §18).
    # ponytail: calibration CV splits by box, not image; group it if LightGBM ever wins.
    return CalibratedClassifierCV(LGBMClassifier(class_weight="balanced", random_state=m["seed"], verbose=-1,
                                                 **m["lightgbm"]), method="sigmoid", cv=3)


def proba_in_order(model, X, classes):
    """predict_proba with columns in `classes` order (a fold may lack a rare class)."""
    p = model.predict_proba(X)
    out = np.zeros((len(X), len(classes)))
    for k, c in enumerate(model.classes_):
        out[:, classes.index(c)] = p[:, k]
    return out


def expected_calibration_error(conf, correct, bins):
    edges = np.linspace(0, 1, bins + 1)
    ece, table = 0.0, []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (conf > lo) & (conf <= hi)
        if sel.any():
            ece += sel.mean() * abs(correct[sel].mean() - conf[sel].mean())
            table.append({"bin": [round(lo, 2), round(hi, 2)], "n": int(sel.sum()),
                          "accuracy": float(correct[sel].mean()), "confidence": float(conf[sel].mean())})
    return float(ece), table


def feature_weights(model, kind, features, top):
    rows = []
    if kind == "logreg":
        lr = model[-1]  # weights on standardized features: comparable across features
        for c, coef in zip(lr.classes_, lr.coef_):
            for rank, k in enumerate(np.argsort(-np.abs(coef))[:top], 1):
                rows.append({"class": c, "rank": rank, "feature": features[k], "weight": round(float(coef[k]), 4)})
    else:  # LightGBM gives global split importance, not per-class weights
        imp = np.mean([cc.estimator.feature_importances_ for cc in model.calibrated_classifiers_], axis=0)
        for rank, k in enumerate(np.argsort(-imp)[:top], 1):
            rows.append({"class": "all", "rank": rank, "feature": features[k], "weight": round(float(imp[k]), 1)})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["logreg", "lightgbm"], default="logreg")
    args = ap.parse_args()

    cfg = load_config()
    base = Path(cfg["paths"]["output_dir"])
    df, features, excluded = load_training_data(cfg)
    X, y, groups = df[features].to_numpy(float), df.label.to_numpy(), df.image_id.to_numpy()
    classes = sorted(set(y))
    out = base / f"test{next_test_number(base)}_{args.model}"
    out.mkdir(parents=True)

    # --- out-of-fold predictions
    proba = np.zeros((len(y), len(classes)))
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=cfg["model"]["cv_folds"]).split(X, y, groups)):
        assert not set(groups[tr]) & set(groups[te]), "a screenshot leaked across the split"
        model = make_model(args.model, cfg).fit(X[tr], y[tr])
        proba[te] = proba_in_order(model, X[te], classes)
        print(f"fold {fold}: {len(set(groups[te]))} test images, {len(te)} boxes")
    pred = np.array(classes)[proba.argmax(1)]
    conf = proba.max(1)

    # --- metrics
    report = classification_report(y, pred, labels=classes, digits=3, zero_division=0)
    p, r, f1, n = precision_recall_fscore_support(y, pred, labels=classes, zero_division=0)
    per_class = {c: {"precision": float(p[k]), "recall": float(r[k]), "f1": float(f1[k]), "support": int(n[k])}
                 for k, c in enumerate(classes)}
    ece, bins = expected_calibration_error(conf, pred == y, cfg["model"]["calibration_bins"])
    cm = confusion_matrix(y, pred, labels=classes)

    group = [c for c in cfg["confusable_group"] if c in classes]
    gi = [classes.index(c) for c in group]
    sub = pd.DataFrame(cm[np.ix_(gi, gi)], index=[f"true {c}" for c in group], columns=group)
    sub["other"] = cm[gi].sum(1) - sub.to_numpy().sum(1)
    group_lines = [f"{c:<15} P {per_class[c]['precision']:.3f}  R {per_class[c]['recall']:.3f}  "
                   f"F1 {per_class[c]['f1']:.3f}  n={per_class[c]['support']}" for c in group]
    (out / "classification_report.txt").write_text(
        f"Class refiner ({args.model}), {cfg['model']['cv_folds']}-fold GroupKFold by image, out-of-fold predictions\n"
        f"{len(y)} boxes, {len(set(groups))} images. Excluded from training: {excluded}\n\n{report}\n"
        f"ECE (top-label, {cfg['model']['calibration_bins']} bins): {ece:.4f}\n\n"
        f"=== Confusable group (design.md §18; YOLO ui16_v1 button recall 0.58) ===\n"
        + "\n".join(group_lines) + "\n\nConfusion within the group (rows = truth):\n"
        + sub.to_string() + "\n", encoding="utf-8")

    (out / "metrics.json").write_text(json.dumps({
        "model": args.model, "accuracy": float((pred == y).mean()),
        "macro_f1": float(f1.mean()), "ece": ece, "per_class": per_class,
        "confusable_group": {c: per_class[c] for c in group}, "calibration_bins": bins,
        "confusion_matrix": {"labels": classes, "matrix": cm.tolist()},
    }, indent=2), encoding="utf-8")

    # --- final model on all data (before the plots: the weight chart needs it)
    final = make_model(args.model, cfg).fit(X, y)
    joblib.dump({"model": final, "features": features, "classes": list(final.classes_), "kind": args.model},
                out / "model.joblib")
    weights = feature_weights(final, args.model, features, cfg["model"]["top_weights_per_class"])
    weights.to_csv(out / "feature_weights.csv", index=False)

    # --- plots + report.html
    tag = f"class refiner ({args.model}), out-of-fold, {len(set(groups))} images"
    plots.confusion(cm, classes, classes, f"Confusion matrix: {tag}", out / "confusion_matrix.png", group,
                    figsize=(11, 9.5))
    plots.confusion(sub.to_numpy(), group, group + ["other"], "Confusable group (rows = truth)",
                    out / "confusion_confusable.png", group)
    order = sorted(classes, key=lambda c: -per_class[c]["f1"])
    plots.grouped_bars([f"{c} *" if c in group else c for c in order],
                       {m: [per_class[c][m] for c in order] for m in ("precision", "recall", "f1")},
                       f"Per-class scores: {tag}", out / "per_class_metrics.png", "score",
                       annotate=[f"n={per_class[c]['support']}" for c in order], group=group)
    plots.reliability(bins, conf, ece, f"Calibration: {args.model}", out / "reliability.png")
    images = [("confusion_matrix.png", "All classes. Cell = count; colour = share of the true class. Red labels = confusable group."),
              ("confusion_confusable.png", "Confusable group only; 'other' = predicted as any class outside the group."),
              ("per_class_metrics.png", "Precision / recall / F1 per class, sorted by F1; * = confusable group."),
              ("reliability.png", "Top: accuracy vs predicted probability (on the diagonal = well calibrated). Bottom: how confident the model is.")]
    if args.model == "logreg":
        plots.weight_panels(weights, group, "Why: top feature weights, confusable group", out / "feature_weights.png")
        images.append(("feature_weights.png", "Top weights per class (full list in feature_weights.csv)."))
    plots.html_report(
        out / "report.html", f"Class refiner: {args.model} ({out.name})",
        [("accuracy", f"{(pred == y).mean():.3f}"), ("macro F1", f"{f1.mean():.3f}"), ("ECE", f"{ece:.3f}"),
         ("button recall (YOLO 0.58)", f"{per_class.get('button', {}).get('recall', float('nan')):.3f}"),
         ("boxes / images", f"{len(y)} / {len(set(groups))}")],
        images,
        [("Per class (out-of-fold)", ["class", "precision", "recall", "F1", "n"],
          [[c + (" *" if c in group else ""), f"{per_class[c]['precision']:.3f}", f"{per_class[c]['recall']:.3f}",
            f"{per_class[c]['f1']:.3f}", per_class[c]["support"]] for c in order]),
         ("Excluded from training", ["class", "boxes"], [[c, v] for c, v in excluded.items()])])

    csv_path = base / "features.csv"
    versions = {"python": platform.python_version(), "sklearn": sklearn.__version__,
                "numpy": np.__version__, "pandas": pd.__version__}
    if args.model == "lightgbm":
        import lightgbm
        versions["lightgbm"] = lightgbm.__version__
    (out / "run_config.json").write_text(json.dumps({
        "command": " ".join(sys.argv), "model": args.model, "features": features,
        "params": cfg["model"], "config_file": str(CONFIG_PATH), "config": cfg,
        "data": {"features_csv": str(csv_path),
                 "features_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                 "boxes": len(y), "images": len(set(groups)),
                 "per_class": {c: int((y == c).sum()) for c in classes},
                 "excluded_from_training": excluded},
        "versions": versions,
    }, indent=2), encoding="utf-8")

    print(report)
    print(f"ECE {ece:.4f}\n" + "\n".join(group_lines))
    print(f"\nexcluded from training: {excluded}\nsaved to {out}")


if __name__ == "__main__":
    main()
