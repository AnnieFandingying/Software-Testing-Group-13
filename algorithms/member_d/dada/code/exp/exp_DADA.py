import os
import torch
import numpy as np
from data_provider.data_provider import data_provider

class DADA(object):
    def __init__(self, args):
        self.args = args
        self.device = self._acquire_device()
        self.model = self._build_model().to(self.device)

    def _build_model(self):
        from transformers import AutoModel
        model = AutoModel.from_pretrained(self.args.model, trust_remote_code=True)
        return model

    def _acquire_device(self):
        if self.args.use_gpu:
            os.environ["CUDA_VISIBLE_DEVICES"] = str(
                self.args.gpu) if not self.args.use_multi_gpu else self.args.devices
            device = torch.device('cuda:{}'.format(self.args.gpu))
            print('Use GPU: cuda:{}'.format(self.args.gpu))
        else:
            device = torch.device('cpu')
            print('Use CPU')
        return device

    def _get_data(self, flag):
        data_set, data_loader = data_provider(
            root_path=self.args.root_path, 
            datasets=self.args.data, 
            batch_size=self.args.batch_size, 
            flag=flag, 
        )
        return data_set, data_loader

    def zero_shot(self, setting):
        folder_path = './test_results/' + setting + '/'
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        test_data, test_loader = self._get_data(flag='test')
        init_data, init_loader = self._get_data(flag='init')  # For SPOT algorithm    

        test_labels = []
        test_scores = []
        init_scores = []
        self.model.eval()
        # cal anomaly_socres
        with torch.no_grad():
            for i, (batch_x, batch_y) in enumerate(init_loader): 
                batch_x = batch_x.float().to(self.device)
                score = self.model.infer(batch_x, norm=self.args.norm)
                score = score.detach().cpu().numpy()
                init_scores.append(score)
            for i, (batch_x, batch_y) in enumerate(test_loader):
                batch_x = batch_x.float().to(self.device)
                score = self.model.infer(batch_x, norm=self.args.norm)
                score = score.detach().cpu().numpy()
                test_scores.append(score)
                test_labels.append(batch_y) 
        init_scores = np.concatenate(init_scores, axis=0).reshape(-1)
        init_scores = np.array(init_scores)
        test_scores = np.concatenate(test_scores, axis=0).reshape(-1)
        test_scores = np.array(test_scores)
        test_labels = np.concatenate(test_labels, axis=0).reshape(-1)
        test_labels = np.array(test_labels)
        gt = test_labels.astype(int)
        
        from ts_ad_evaluation import Evaluator
        evaluator = Evaluator(gt, test_scores, folder_path)
        evaluator.evaluate(metrics=self.args.metric, affiliation=self.args.t)  

