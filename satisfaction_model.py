import torch
import torch.nn as nn
import torch.optim as optim

# --- 1. ニューラルネットワークの定義 ---
class SatisfactionModel(nn.Module):
    def __init__(self):
        super(SatisfactionModel, self).__init__()
        # 入力: [土日出勤数, 連勤数, 休み希望却下数] の3つ
        self.fc1 = nn.Linear(3, 8)
        self.fc2 = nn.Linear(8, 1)
        self.sigmoid = nn.Sigmoid() # 出力を0.0〜1.0に収める

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = self.sigmoid(self.fc2(x))
        return x

# --- 2. 準備 ---
model = SatisfactionModel()
criterion = nn.MSELoss() # 誤差の計算方法
optimizer = optim.Adam(model.parameters(), lr=0.01)

# --- 3. 学習データの準備（例） ---
# [土日回数, 連勤数, 却下数]
X_train = torch.tensor([
    [10.0, 0.0, 0.0], # 土日ばかりで不満
    [0.0, 5.0, 1.0],  # 土日は少ないが連勤で不満
    [1.0, 1.0, 0.0]   # バランスが良くて満足
], dtype=torch.float32)

# 正解データ（0:満足, 1:不満爆発）
y_train = torch.tensor([[0.9], [0.7], [0.1]], dtype=torch.float32)

# --- 4. 簡単な学習ループ ---
for epoch in range(100):
    optimizer.zero_grad()
    outputs = model(X_train)
    loss = criterion(outputs, y_train)
    loss.backward()
    optimizer.step()

# --- 5. 予測のテスト ---
# Aさんの状況：土日がすでに5回、連勤が3回ある場合
test_data = torch.tensor([[5.0, 3.0, 0.0]], dtype=torch.float32)
prediction = model(test_data)

print(f"予測される不満度スコア: {prediction.item():.4f}")