# ────────────────────────────────────────────────────────────────
# build_mf.py — train an implicit-feedback Matrix-Factorisation model
# using Alternating Least Squares (ALS) from the `implicit` library
# ────────────────────────────────────────────────────────────────
# example:
#   python src/build_mf.py \
#          --ratings   data/processed/ratings_mapped.csv \
#          --processed data/processed/movies_processed.csv \
#          --factors   64 \
#          --iters     15 \
#          --alpha     40 \
#          --reg       0.01
# ────────────────────────────────────────────────────────────────
import argparse, json, os
from pathlib import Path
import numpy as np
import pandas as pd
import scipy.sparse as sp
from implicit.cpu.als import AlternatingLeastSquares  # ALS model

# ────────────────────────────────────────────────────────────────
def build_confidence(ratings: pd.DataFrame, user2row: dict, item2col: dict, alpha: float = 40.0) -> sp.coo_matrix:
    """
    Construct a confidence matrix from raw ratings using:
    C_ui = 1 + α · r_ui  (as per Hu et al., 2008)
    """
    rows = ratings["userId"].map(user2row.get).astype(np.int32)
    cols = ratings["movieId"].map(item2col.get).astype(np.int32)
    vals = 1.0 + alpha * ratings["rating"].astype(np.float32)

    return sp.coo_matrix(
        (vals, (rows, cols)),
        shape=(len(user2row), len(item2col)),
        dtype=np.float32,
    )

# ────────────────────────────────────────────────────────────────
def main() -> None:
    # Limit number of BLAS threads to keep CPU calm
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

    # Setup CLI arguments
    ap = argparse.ArgumentParser(
        description="Train an implicit-feedback ALS model (cpu.als)"
    )
    # Input files
    ap.add_argument("--ratings",   default="data/processed/ratings_mapped.csv",
                    help="CSV with userId, movieId, rating")
    ap.add_argument("--processed", default="data/processed/movies_processed.csv",
                    help="movies_processed.csv (defines item order)")
    # Output files
    ap.add_argument("--out",       default="models/als_model.npz")
    ap.add_argument("--mappings",  default="models/mf_mappings.json")
    # ALS hyperparameters
    ap.add_argument("--factors", type=int,   default=128)
    ap.add_argument("--iters",   type=int,   default=20)
    ap.add_argument("--alpha",   type=float, default=40.0)
    ap.add_argument("--reg",     type=float, default=0.01)
    # Sparsity filters
    ap.add_argument("--min-user-cnt", type=int, default=5,
                    help="drop users with <N interactions")
    ap.add_argument("--min-item-cnt", type=int, default=20,
                    help="drop items with <N interactions")
    args = ap.parse_args()

    # ══════════ 1) Load data ════════════════════════════════════
    print("• loading ratings  …")
    ratings = pd.read_csv(args.ratings)  # userId, movieId, rating
    print(f"  raw rows        : {len(ratings):,}")

    print("• loading metadata …")
    # Load item metadata to define item index space
    movies  = (
        pd.read_csv(args.processed, usecols=["id"])
          .drop_duplicates("id")
          .reset_index(drop=True)
    )
    all_item_ids = movies["id"].values

    # ══════════ 2) Prune by user/item interaction counts ════════
    if args.min_user_cnt > 0:
        vc = ratings["userId"].value_counts()
        keep_u = set(vc[vc >= args.min_user_cnt].index)
        ratings = ratings[ratings.userId.isin(keep_u)]

    if args.min_item_cnt > 0:
        vc = ratings["movieId"].value_counts()
        keep_i = set(vc[vc >= args.min_item_cnt].index)
        ratings = ratings[ratings.movieId.isin(keep_i)]

    # Keep only items present in processed metadata
    ratings = ratings[ratings.movieId.isin(all_item_ids)]
    print(f"  kept rows       : {len(ratings):,}")

    # ══════════ 3) Build user/item index maps ═══════════════════
    user_ids = ratings["userId"].unique()        # unordered
    item_ids = all_item_ids                      # preserve metadata order

    user2row = {uid: i for i, uid in enumerate(user_ids)}
    item2col = {iid: i for i, iid in enumerate(item_ids)}
    print(f"  users={len(user2row):,}  items={len(item2col):,}")

    # ══════════ 4) Build sparse confidence matrix ═══════════════
    C = build_confidence(ratings, user2row, item2col, alpha=args.alpha)

    # ══════════ 5) Train ALS model ══════════════════════════════
    print(f"• training ALS  (factors={args.factors}  iters={args.iters}) …")
    als = AlternatingLeastSquares(
        factors=args.factors,
        regularization=args.reg,
        iterations=args.iters,
    )
    # Use CSR format for fast training
    als.fit(C.tocsr(), show_progress=True)

    # ══════════ 6) Save model artefacts ═════════════════════════
    # Save user/item embeddings
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.out,
             user_factors=als.user_factors.astype(np.float32),
             item_factors=als.item_factors.astype(np.float32))
    print(f"✔ factors saved  →  {args.out}")

    # Save id-to-index mappings (and reverse)
    mappings = {
        "user2row": {int(k): int(v) for k, v in user2row.items()},
        "item2col": {int(k): int(v) for k, v in item2col.items()},
        "row2user": {int(v): int(k) for k, v in user2row.items()},
        "col2item": {int(v): int(k) for k, v in item2col.items()},
    }
    Path(args.mappings).parent.mkdir(parents=True, exist_ok=True)
    Path(args.mappings).write_text(json.dumps(mappings))
    print(f"✔ mappings saved →  {args.mappings}")

# ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()  # Entry point
